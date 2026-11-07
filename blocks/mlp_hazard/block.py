"""mlp_hazard: a residual MLP with piecewise-linear numerical embeddings, on the GPU.

One forward pass per snapshot gives the 7 bin logits, so there is no person-period
expansion. The loss is a masked per-bin binary cross-entropy built from the rules of
survival.expand (at-risk bins, the event bin, actuarial exposure for censored rows), with
weight ** 0.5. The whole training set sits on the GPU and batches are taken by indexing.

Heavy-tailed counters: signed log1p, then piecewise-linear encoding on train quantile edges
(plus a clipped standardized copy). NaN: filled with the train median, plus a
missing-indicator channel for every feature that has NaN in train. model_code and
vendor_code: embeddings. Everything is fitted on train only and saved for predict.
"""

from __future__ import annotations

import copy
import math
import time

import numpy as np
import torch
from torch import nn

SEED = 20241
WEIGHT_POWER = 0.5
BINS = 16               # piecewise-linear bins per numerical feature
EMB = 8                 # width of each numerical feature embedding
WIDTH = 512
BLOCKS = 4
HIDDEN = 1024
DROPOUT = 0.3
BATCH = 16384
SMALL_BATCH = 4096
LR = 2e-3
WEIGHT_DECAY = 0.1
WARMUP = 0.05           # share of a cycle
EMA_DECAY = 0.999
EVAL_EVERY = 0.5        # epochs between evaluations on `stop`
PATIENCE = 6            # evaluations without improvement before a member stops
CYCLE_EPOCHS = 10       # epochs of one member's cosine cycle (at most)
MIN_CYCLE_EPOCHS = 3
MIN_MEMBERS = 5         # the budget is spread so that about this many members fit
MAX_MEMBERS = 16
MIN_EVAL_STEPS = 20
SAFETY = 20             # seconds kept before the deadline
FIT_SAMPLE = 1_000_000  # rows used to fit quantile edges
EVAL_CHUNK = 8192
PREDICT_CHUNK = 16384
ZERO_EPS = 1e-3         # minimum width of a piecewise-linear bin (log space)
USE_HIST = True         # add the change since a few lags back, from `hist`
HIST_LAGS = [3, 7, 14, 30, 90, 365]
DROPOUTS = [0.3, 0.4, 0.2]   # members take these in turn, for variety
LRS = [2e-3, 3e-3, 1.5e-3]

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ---------------------------------------------------------------- preprocessing

def _slog(x: torch.Tensor) -> torch.Tensor:
    return torch.sign(x) * torch.log1p(torch.abs(x))


class Prep:
    """Train-fitted input transform: everything predict needs, as plain tensors."""

    def __init__(self, features, categorical, lags=None):
        self.features = list(features)
        # positions in hist's lag axis: lag 0 first, then the lags whose change is used
        self.lag_idx = [] if not USE_HIST else [lags.index(0)] + [lags.index(l) for l in HIST_LAGS]
        self.cat_names = [f for f in features if f in categorical]
        self.cat_sizes = [len(categorical[f]) for f in self.cat_names]
        self.cat_idx = [self.features.index(f) for f in self.cat_names]
        self.num_idx = [i for i, f in enumerate(self.features) if f not in categorical]
        self.edges = self.mean = self.std = self.fill = None
        self.miss_idx = None            # positions (within numerics) that get a missing flag

    def numeric(self, X: torch.Tensor, H):
        """Signed-log numerics, then the hist changes (NaN where the lag does not exist)."""
        num = _slog(X[:, self.num_idx])
        if self.lag_idx:
            h = H.float()
            delta = h[:, 1:, :] - h[:, :1, :]
            num = torch.cat([num, delta.flatten(1)], dim=1)
        return num

    def fit(self, X: torch.Tensor, H) -> None:
        """X: raw float32 (n, features) and H: float16 (n, 1 + lags, columns), on the device."""
        g = torch.Generator(device=X.device).manual_seed(SEED)
        rows = torch.randperm(X.shape[0], device=X.device, generator=g)[:FIT_SAMPLE]
        sub = self.numeric(X[rows], H[rows] if self.lag_idx else None)
        num = sub
        q = torch.linspace(0, 1, BINS + 1, device=num.device)
        edges, mean, std, fill = [], [], [], []
        for j in range(sub.shape[1]):
            col = sub[:, j]
            col = col[~torch.isnan(col)]
            if col.numel() == 0:
                col = torch.zeros(1, device=num.device)
            edges.append(torch.quantile(col, q))
            mean.append(col.mean())
            std.append(col.std().clamp_min(1e-3) if col.numel() > 1 else torch.ones((), device=num.device))
            fill.append(torch.median(col))
        self.edges = torch.stack(edges)                       # (F, BINS + 1)
        self.mean, self.std, self.fill = (torch.stack(v) for v in (mean, std, fill))
        self.miss_idx = torch.nonzero(torch.isnan(num).any(dim=0)).flatten()

    def encode(self, X: torch.Tensor, H=None):
        """Raw (n, features) -> (signed-log numerics with NaN filled, missing flags, codes)."""
        num = self.numeric(X, H)
        nan = torch.isnan(num)
        miss = nan[:, self.miss_idx].to(torch.uint8)
        num = torch.where(nan, self.fill.expand_as(num), num)
        codes = torch.stack([X[:, i].nan_to_num(0.0).round().long().clamp(0, s - 1)
                             for i, s in zip(self.cat_idx, self.cat_sizes)], dim=1)
        return num, miss, codes

    def state(self) -> dict:
        return {"features": self.features, "cat_names": self.cat_names,
                "cat_sizes": self.cat_sizes, "edges": self.edges.cpu(), "mean": self.mean.cpu(),
                "std": self.std.cpu(), "fill": self.fill.cpu(), "miss_idx": self.miss_idx.cpu(),
                "lag_idx": self.lag_idx}

    @classmethod
    def from_state(cls, s: dict, device) -> "Prep":
        p = cls.__new__(cls)
        p.features, p.cat_names, p.cat_sizes = s["features"], s["cat_names"], s["cat_sizes"]
        p.cat_idx = [p.features.index(f) for f in p.cat_names]
        p.lag_idx = s["lag_idx"]
        p.num_idx = [i for i, f in enumerate(p.features) if f not in p.cat_names]
        p.edges, p.mean, p.std, p.fill, p.miss_idx = (s[k].to(device) for k in
                                                      ("edges", "mean", "std", "fill", "miss_idx"))
        return p


# ---------------------------------------------------------------- model

class Net(nn.Module):
    def __init__(self, n_num, n_miss, cat_sizes, n_out, edges, mean, std, dropout=DROPOUT):
        super().__init__()
        self.register_buffer("lo", edges[:, :-1].clone())
        self.register_buffer("width", (edges[:, 1:] - edges[:, :-1]).clamp_min(ZERO_EPS))
        self.register_buffer("mean", mean.clone())
        self.register_buffer("std", std.clone())
        k = BINS + 1
        self.w = nn.Parameter(torch.randn(n_num, k, EMB) / math.sqrt(k))
        self.b = nn.Parameter(torch.zeros(n_num, EMB))
        self.cats = nn.ModuleList(nn.Embedding(s, min(16, max(4, s // 4 + 1))) for s in cat_sizes)
        d_in = n_num * EMB + sum(c.embedding_dim for c in self.cats) + n_miss
        self.inp = nn.Linear(d_in, WIDTH)
        self.blocks = nn.ModuleList(
            nn.Sequential(nn.LayerNorm(WIDTH), nn.Linear(WIDTH, HIDDEN), nn.GELU(),
                          nn.Dropout(dropout), nn.Linear(HIDDEN, WIDTH))
            for _ in range(BLOCKS))
        self.drop = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(WIDTH)
        self.out = nn.Linear(WIDTH, n_out)

    def forward(self, num, miss, codes):
        with torch.autocast(DEVICE.type, enabled=False):
            ple = ((num.unsqueeze(-1) - self.lo) / self.width).clamp(0, 1)         # (B, F, BINS)
            lin = ((num - self.mean) / self.std).clamp(-5, 5).unsqueeze(-1)       # (B, F, 1)
            z = torch.cat([ple, lin], dim=-1)
            z = torch.relu(torch.einsum("bfk,fke->bfe", z, self.w) + self.b)
            parts = [z.flatten(1)] + [e(codes[:, i]) for i, e in enumerate(self.cats)]
            parts.append(miss.float())
            h = torch.cat(parts, dim=1)
        h = self.inp(h)
        for blk in self.blocks:
            h = h + self.drop(blk(h))
        return self.out(self.norm(h)).float()


# ---------------------------------------------------------------- targets

def _targets(meta, edges, power):
    """Dense (n, K) labels and weights with the rules of survival.expand."""
    d = meta["duration_days"].to_numpy(np.int64)
    e = meta["event"].to_numpy(bool)
    w = meta["weight"].to_numpy(np.float64) ** power
    K = len(edges) - 1
    y = np.zeros((len(d), K), np.uint8)
    wt = np.zeros((len(d), K), np.float32)
    for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        at_risk = d >= a
        y[:, k] = e & (d < b) & at_risk
        exposure = np.where(~e & (d < b - 1), (d - a + 1) / (b - a), 1.0)
        wt[:, k] = np.where(at_risk, w * exposure, 0.0)
    return y, wt


def _load_hist(hist, lag_idx, chunk=262144):
    """The needed lags of a memory-mapped hist, in chunks, as float16 on the device."""
    out = torch.empty((hist.shape[0], len(lag_idx), hist.shape[2]), dtype=torch.float16, device=DEVICE)
    for lo in range(0, hist.shape[0], chunk):
        out[lo:lo + chunk] = torch.from_numpy(np.ascontiguousarray(hist[lo:lo + chunk][:, lag_idx, :]))
    return out


class _Set:
    """A part on the device: raw X, labels and weights."""

    def __init__(self, part, edges, lags=None):
        self.X = torch.from_numpy(np.array(part.X, dtype=np.float32)).to(DEVICE)
        self.H = _load_hist(part.hist, lags) if lags else None
        y, wt = _targets(part.meta, edges, WEIGHT_POWER)
        self.y = torch.from_numpy(y).to(DEVICE)
        self.wt = torch.from_numpy(wt).to(DEVICE)


def prepare(data, model_dir):
    lag_idx = Prep(data.features, data.categorical, data.lags).lag_idx
    return (_Set(data.train, data.bin_edges, lag_idx), _Set(data.stop, data.bin_edges, lag_idx))


# ---------------------------------------------------------------- training

def _loss(logits, y, wt, scale):
    bce = nn.functional.binary_cross_entropy_with_logits(logits, y.float(), reduction="none")
    return (bce * wt).sum() / (logits.shape[0] * scale)


def _save(path, net, prep, extra):
    tmp = path.with_suffix(".tmp")
    torch.save({"net": {k: v.cpu() for k, v in net.state_dict().items()},
                "prep": prep.state(), **extra}, tmp)
    tmp.replace(path)


def _make_net(prep, num, miss, n_out, base, dropout):
    net = Net(num.shape[1], miss.shape[1], prep.cat_sizes, n_out, prep.edges, prep.mean,
              prep.std, dropout).to(DEVICE)
    with torch.no_grad():                                              # start at the base hazard
        net.out.bias.copy_(torch.logit(base.clamp(1e-6, 0.5)))
        net.out.weight.mul_(0.1)
    return net


def _optimizer(net, lr):
    decay, no_decay = [], []
    for name, p in net.named_parameters():
        (no_decay if p.ndim < 2 or name.startswith("cats") or name == "b" else decay).append(p)
    groups = [{"params": decay, "weight_decay": WEIGHT_DECAY},
              {"params": no_decay, "weight_decay": 0.0}]
    try:
        return torch.optim.AdamW(groups, lr=lr, betas=(0.9, 0.99), fused=True)
    except (RuntimeError, ValueError):
        return torch.optim.AdamW(groups, lr=lr, betas=(0.9, 0.99))


def fit(data, model_dir, deadline, state):
    """A seed ensemble. Each member is one short cosine cycle with an EMA of its weights; the
    best EMA checkpoint on `stop` is saved as soon as it appears, so the deadline never
    loses a model. Members keep being trained until the budget is spent."""
    t0 = time.time()
    train, stop = state
    prep = Prep(data.features, data.categorical, data.lags)
    prep.fit(train.X, train.H)
    n = train.X.shape[0]
    num = miss = codes = None
    for lo in range(0, n, 262144):          # encode in chunks into preallocated storage
        sl = slice(lo, lo + 262144)
        c = prep.encode(train.X[sl], None if train.H is None else train.H[sl])
        if num is None:
            num, miss, codes = (torch.empty((n, *t.shape[1:]), dtype=t.dtype, device=DEVICE) for t in c)
        num[sl], miss[sl], codes[sl] = c
    snum, smiss, scodes = prep.encode(stop.X, stop.H)
    del train.X, stop.X, train.H, stop.H
    print("features:", data.features, flush=True)

    K = len(data.bin_edges) - 1
    scale = float(train.wt.sum() / max(1, (train.wt > 0).sum()))      # mean weight of used cells
    base = (train.wt * train.y).sum(0) / train.wt.sum(0).clamp_min(1e-9)
    batch = BATCH if n >= 1_000_000 else SMALL_BATCH    # a small set (smoke) cannot afford a big batch
    steps_per_epoch = max(1, n // batch)
    eval_every = max(MIN_EVAL_STEPS, int(steps_per_epoch * EVAL_EVERY))
    limit = deadline - SAFETY

    @torch.no_grad()
    def stop_logits(model):
        model.eval()
        out = []
        for lo in range(0, snum.shape[0], EVAL_CHUNK):
            sl = slice(lo, lo + EVAL_CHUNK)
            with torch.autocast(DEVICE.type, dtype=torch.bfloat16):
                out.append(model(snum[sl], smiss[sl], scodes[sl]).float())
        return torch.cat(out)

    def stop_loss(z):
        bce = nn.functional.binary_cross_entropy_with_logits(z, stop.y.float(), reduction="none")
        return float((bce * stop.wt).sum() / (z.shape[0] * scale))

    print(f"mlp_hazard: {n} train rows, {steps_per_epoch} steps/epoch, setup "
          f"{time.time() - t0:.1f}s, budget {limit - time.time():.0f}s", flush=True)
    members, member_logits, epoch_seconds = [], [], None
    for m in range(MAX_MEMBERS):
        now = time.time()
        if limit - now < 20:
            break
        torch.manual_seed(SEED + m)
        gen = torch.Generator(device=DEVICE).manual_seed(SEED + m)
        epochs = CYCLE_EPOCHS
        if epoch_seconds is not None:             # spread the rest of the budget over members
            epochs = int(min(CYCLE_EPOCHS, max(MIN_CYCLE_EPOCHS, (limit - now) / epoch_seconds
                                               / max(1, MIN_MEMBERS - m))))
            epochs = int(min(epochs, (limit - now) / epoch_seconds))
            if epochs < MIN_CYCLE_EPOCHS:
                break
        total = max(1, epochs * steps_per_epoch)
        dropout, member_lr = DROPOUTS[m % len(DROPOUTS)], LRS[m % len(LRS)]
        net = _make_net(prep, num, miss, K, base, dropout)
        ema = copy.deepcopy(net).eval()
        for p in ema.parameters():
            p.requires_grad_(False)
        opt = _optimizer(net, member_lr)
        best, bad, best_z, losses, perm, pos, start = float("inf"), 0, None, [], None, n, time.time()
        for step in range(1, total + 1):
            if step % 20 == 0 and time.time() > limit:
                break
            if pos + batch > n:
                perm, pos = torch.randperm(n, device=DEVICE, generator=gen), 0
            idx = perm[pos:pos + batch]
            pos += batch
            warm = min(1.0, step / max(1, int(WARMUP * total)))
            lr = member_lr * warm * (0.5 * (1 + math.cos(math.pi * step / total)) * 0.98 + 0.02)
            for g in opt.param_groups:
                g["lr"] = lr
            net.train()
            with torch.autocast(DEVICE.type, dtype=torch.bfloat16):
                z = net(num[idx], miss[idx], codes[idx])
            loss = _loss(z, train.y[idx], train.wt[idx], scale)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            opt.step()
            d = min(EMA_DECAY, (1 + step) / (10 + step))
            with torch.no_grad():
                for pe, pn in zip(ema.parameters(), net.parameters()):
                    pe.lerp_(pn, 1 - d)
            losses.append(loss.detach())
            if step % eval_every == 0 or step == total:
                z_stop = stop_logits(ema)
                v = stop_loss(z_stop)
                tr = float(torch.stack(losses).mean())
                losses.clear()
                if v < best - 1e-6:
                    best, bad, best_z = v, 0, z_stop
                    _save(model_dir / f"member{m}.pt", ema, prep,
                          {"stop_loss": v, "step": step, "dropout": dropout})
                else:
                    bad += 1
                print(f"member {m} step {step}/{total} epoch {step / steps_per_epoch:.1f} "
                      f"t {time.time() - t0:.0f}s lr {lr:.2e} train {tr:.5f} stop {v:.5f}"
                      f"{' *' if bad == 0 else ''}", flush=True)
                if bad >= PATIENCE:
                    break
        if best_z is None:
            break
        if epoch_seconds is None or step >= total:
            epoch_seconds = (time.time() - start) / max(1, step / steps_per_epoch)
        members.append(m)
        member_logits.append(best_z)
        ens = stop_loss(torch.stack(member_logits).mean(0))
        print(f"member {m} done: best stop {best:.5f}; ensemble of {len(members)}: {ens:.5f}; "
              f"{epoch_seconds:.1f}s/epoch", flush=True)
        del net, ema, opt
    if DEVICE.type == "cuda":
        print(f"mlp_hazard: {len(members)} members; peak VRAM "
              f"{torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)
    if not members:
        raise RuntimeError("no member was trained")


# ---------------------------------------------------------------- inference

def load(model_dir):
    nets = []
    for path in sorted(model_dir.glob("member*.pt")):
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        prep = Prep.from_state(ckpt["prep"], DEVICE)
        net = Net(prep.edges.shape[0], len(prep.miss_idx), prep.cat_sizes,
                  ckpt["net"]["out.bias"].shape[0], prep.edges, prep.mean, prep.std)
        net.load_state_dict(ckpt["net"])
        nets.append(net.to(DEVICE).eval())
    return nets, prep


@torch.no_grad()
def predict(model, X, hist):
    nets, prep = model
    out = []
    for lo in range(0, len(X), PREDICT_CHUNK):
        x = torch.from_numpy(np.asarray(X[lo:lo + PREDICT_CHUNK], dtype=np.float32)).to(DEVICE)
        h = None
        if prep.lag_idx:
            h = torch.from_numpy(np.ascontiguousarray(
                np.asarray(hist[lo:lo + PREDICT_CHUNK])[:, prep.lag_idx, :])).to(DEVICE)
        num, miss, codes = prep.encode(x, h)
        z = 0.0
        for net in nets:
            with torch.autocast(DEVICE.type, dtype=torch.bfloat16):
                z = z + net(num, miss, codes).float()
        z = z / len(nets)
        out.append(z.nan_to_num(0.0, 30.0, -30.0).clamp(-30, 30).cpu())
    return torch.cat(out).numpy()

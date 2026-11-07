"""seq_hist, round 2: a short-cycle ensemble of lag-sequence transformers.

Round 1 found the best stop loss after about 1.6 epochs; everything after that overfit. The
4M rows come from about 24k drives, so more passes buy nothing. This round spends the
budget on variance reduction instead:

- Members: many short cycles, each a full warmup-and-cosine anneal of about 100 seconds (a
  little over one epoch). Every member keeps its best snapshot by stop loss. A member joins
  the ensemble only if it lowers the stop loss of the averaged logits (greedy selection);
  the ensemble is saved after each join, so the deadline never loses it.
- Sampling: members alternate between plain shuffled epochs and drive-balanced draws
  (row probability ~ rows_of_drive ** -0.5), so near-copies of one drive and the daily rows
  before a failure do not dominate.
- Inputs built for drift: lag tokens carry only changes against the current reading (log
  ratios of counters) plus NaN masks, no levels. The context token adds the hist_gbdt
  engineered features (growth windows, slopes, accelerations...) to the X features.
  capacity_tb is dropped, days_in_service is heavily jittered, model_code is often hidden.
- Loss: masked per-bin BCE following survival.expand, weight ** 0.5 (exposure linear).
"""

from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from hist_features import NAMES, make_features
from survival import expand, known_status

SEED = 42
WEIGHT_POWER = 0.5
D_MODEL = 96
HEADS = 4
LAYERS = 3
DROPOUTS = [0.3, 0.4]            # members take these in turn
# the 1.5 GiB smoke cap cannot hold 4096-row activations; the full run (13.5 GiB) can
SMALL_GPU = float(os.environ.get("HDA_VRAM_GIB", 99)) < 4
BATCH = 1024 if SMALL_GPU else 4096
INFER_BATCH = 2048 if SMALL_GPU else 8192
PEAK_LR = 4e-4
WEIGHT_DECAY = 0.05
WARMUP_STEPS = 100
FEAT_NOISE = 0.15                # gaussian jitter on standardised inputs, training only
DAYS_NOISE = 0.6                 # extra jitter on days_in_service
TOKEN_DROP = 0.1                 # P(a lag token is blanked to "missing"), training only
MODEL_DROP = 0.25                # P(model_code hidden), training only
BALANCE_POWER = 0.5              # drive-balanced members: row probability ~ rows_of_drive ** -p
CYCLE_SECONDS = float(os.environ.get("HDA_CYCLE_SECONDS", 100))   # target length of one member
EVAL_FRACTIONS = (0.5, 0.7, 0.85, 1.0)   # of a member's time
MIN_EVAL_GAP = 3                 # seconds
STOP_MARGIN = 20                 # seconds kept before the deadline
FIT_SAMPLE = 200_000
CLIP = 8.0
LOG_COLS = ("_raw", "_d7", "_d30")
DROP_INPUTS = ("capacity_tb",)   # absolute fleet scale: drifts, the model embedding carries it
FEATURE_BLOCK = 65_536
THREADS = int(os.environ.get("HDA_THREADS", 4))


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def log(*parts) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *parts, flush=True)


# ---------------------------------------------------------------- inputs

class Prep:
    """Fixed input transform, fitted on a train sample and saved with the model."""

    def __init__(self, features, n_models, n_vendors):
        self.features = list(features)
        self.names = self.features + list(NAMES)
        self.n_models, self.n_vendors = n_models, n_vendors
        self.cat = [self.names.index(c) for c in ("model_code", "vendor_code")]
        skip = {"model_code", "vendor_code", *DROP_INPUTS}
        self.num = [i for i, n in enumerate(self.names) if n not in skip]
        base = set(self.features)
        self.log = [j for j, i in enumerate(self.num) if self.names[i] in base and (
            self.names[i].endswith(LOG_COLS) or self.names[i] == "days_in_service")]
        self.days = self.num.index(self.names.index("days_in_service"))
        self.mu = self.sd = self.hsd = None

    # context features: signed log1p for counters, then standardise; NaN stays NaN
    def raw_num(self, Fm):
        v = Fm[:, self.num]
        v = torch.where(torch.isfinite(v), v, torch.full_like(v, float("nan")))
        if self.log:
            t = v[:, self.log]
            v[:, self.log] = torch.sign(t) * torch.log1p(torch.abs(t))
        return v

    def feat(self, Fm):
        return ((self.raw_num(Fm) - self.mu) / self.sd).clamp(-CLIP, CLIP).half()

    def cats(self, Fm):
        c = torch.nan_to_num(Fm[:, self.cat], nan=-1.0)
        m = c[:, 0].long().clamp(-1, self.n_models) + 1              # 0 = unknown
        m = torch.where(m > self.n_models, torch.zeros_like(m), m)
        v = c[:, 1].long().clamp(-1, self.n_vendors) + 1
        v = torch.where(v > self.n_vendors, torch.zeros_like(v), v)
        return torch.stack([m, v], dim=1).to(torch.int16)

    # lag tokens: change against the current reading, in units of that column's spread
    def hist(self, H):
        h = H.float()
        d = (h - h[:, :1]) / self.hsd
        d = torch.where(torch.isfinite(d), d, torch.full_like(d, float("nan")))
        return d.clamp(-CLIP, CLIP).half()

    def fit(self, Fm, H):
        v = self.raw_num(Fm)
        mu = torch.nanmean(v, dim=0)
        var = torch.nanmean((v - mu) ** 2, dim=0)
        self.mu = torch.nan_to_num(mu)
        self.sd = torch.nan_to_num(var.sqrt(), nan=1.0).clamp_min(1e-3)
        h = H.float()
        d = h - h[:, :1]
        d = torch.where(torch.isfinite(d), d, torch.full_like(d, float("nan")))
        dv = torch.nanmean(d ** 2, dim=(0, 1))
        self.hsd = torch.nan_to_num(dv.sqrt(), nan=1.0).clamp_min(1e-2)

    def state(self):
        return {"mu": self.mu.cpu(), "sd": self.sd.cpu(), "hsd": self.hsd.cpu()}

    def set_state(self, s, dev):
        self.mu, self.sd, self.hsd = (s[k].to(dev) for k in ("mu", "sd", "hsd"))


def split_nan(t):
    m = torch.isnan(t)
    return torch.where(m, torch.zeros_like(t), t).float(), m.float()


# ---------------------------------------------------------------- data on the GPU

def to_device(arr, dev, dtype, chunk: int = 1 << 18) -> torch.Tensor:
    out = torch.empty(arr.shape, dtype=dtype, device=dev)
    for lo in range(0, len(arr), chunk):
        out[lo:lo + chunk] = torch.from_numpy(np.array(arr[lo:lo + chunk])).to(dev)
    return out


def engineered(part, dev):
    """make_features over memory-mapped X and hist, in blocks on a few threads, to the GPU."""
    n = part.X.shape[0]
    first = make_features(np.array(part.X[:2]), np.array(part.hist[:2]))
    out = torch.empty((n, first.shape[1]), dtype=torch.float32, device=dev)

    def work(lo):
        return make_features(np.array(part.X[lo:lo + FEATURE_BLOCK]),
                             np.array(part.hist[lo:lo + FEATURE_BLOCK]))

    starts = range(0, n, FEATURE_BLOCK)
    with ThreadPoolExecutor(max(1, THREADS)) as pool:
        for lo, block in zip(starts, pool.map(work, starts)):
            out[lo:lo + len(block)] = torch.from_numpy(block).to(dev)
    return out


def targets(meta, edges, dev):
    """Per-row (n, K) label and loss weight following survival.expand. Weight is zero in
    bins where the row is not at risk. Censored rows carry their actuarial exposure."""
    d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, w_rows = expand(d, e, w, edges)
    w = np.asarray(w, dtype=np.float64)
    exposure = w_rows / w[idx]
    w_rows = w[idx] ** WEIGHT_POWER * exposure
    Y = torch.zeros(len(meta), len(edges) - 1, dtype=torch.int8)
    W = torch.zeros(len(meta), len(edges) - 1, dtype=torch.float32)
    idx_t, bins_t = torch.from_numpy(idx), torch.from_numpy(bins.astype(np.int64))
    Y[idx_t, bins_t] = torch.from_numpy(y)
    W[idx_t, bins_t] = torch.from_numpy(w_rows.astype(np.float32))
    return Y.to(dev), W.to(dev)


class Split:
    def __init__(self, part, edges, dev, horizon=30):
        t = time.time()
        self.F = engineered(part, dev)            # raw features; becomes Xz in fit
        self.H = to_device(part.hist, dev, torch.float16)
        self.Y, self.W = targets(part.meta, edges, dev)
        m = part.meta
        self.drive = np.unique(m["serial_number"].to_numpy(), return_inverse=True)[1]
        status = known_status(m["duration_days"].to_numpy(), m["event"].to_numpy(), horizon)
        keep = status >= 0
        self.ap_y = torch.from_numpy((status[keep] == 1).astype(np.float32)).to(dev)
        self.ap_w = torch.from_numpy(m["weight"].to_numpy()[keep].astype(np.float32)).to(dev)
        self.ap_rows = torch.from_numpy(np.flatnonzero(keep)).to(dev)
        self.ap_bins = edges.index(horizon)
        self.Xz = self.C = None
        self.seconds = time.time() - t

    def __len__(self):
        return self.F.shape[0] if self.F is not None else self.Xz.shape[0]

    def transform(self, prep, chunk: int = 1 << 18):
        """Raw features and hist -> model inputs, in place of the raw tensors."""
        n = len(self)
        self.Xz = torch.empty((n, len(prep.num)), dtype=torch.float16, device=self.F.device)
        self.C = torch.empty((n, 2), dtype=torch.int16, device=self.F.device)
        for lo in range(0, n, chunk):
            Fm = self.F[lo:lo + chunk]
            self.Xz[lo:lo + chunk] = prep.feat(Fm)
            self.C[lo:lo + chunk] = prep.cats(Fm)
            self.H[lo:lo + chunk] = prep.hist(self.H[lo:lo + chunk])
        self.F = None


def prepare(data, model_dir):
    dev = device()
    edges = data.bin_edges
    train = Split(data.train, edges, dev)
    stop = Split(data.stop, edges, dev)
    log(f"prepared: train {len(train)} rows ({train.seconds:.0f}s), stop {len(stop)} rows, "
        f"{train.F.shape[1]} features, {len(set(train.drive.tolist()))} drives"
        + (f", gpu {torch.cuda.memory_allocated() / 2**30:.2f} GiB" if dev.type == "cuda" else ""))
    return train, stop


# ---------------------------------------------------------------- the network

class SeqNet(nn.Module):
    def __init__(self, n_ctx, n_hcols, lags, n_models, n_vendors, k, dropout):
        super().__init__()
        d = D_MODEL
        lags = np.asarray(lags, dtype=np.float32)
        gap = np.diff(lags, append=lags[-1] + (lags[-1] - lags[-2]))
        pos = np.stack([np.log1p(lags), np.log1p(gap), lags / lags.max()], axis=1)
        self.register_buffer("pos", torch.from_numpy(pos.astype(np.float32)), persistent=False)
        self.tok = nn.Linear(2 * n_hcols, d)
        self.pos_mlp = nn.Sequential(nn.Linear(3, d), nn.GELU(), nn.Linear(d, d))
        self.lag_emb = nn.Embedding(len(lags), d)
        self.model_emb = nn.Embedding(n_models + 1, 16)
        self.vendor_emb = nn.Embedding(n_vendors + 1, 4)
        self.ctx = nn.Sequential(nn.Linear(n_ctx + 20, 256), nn.GELU(), nn.Dropout(dropout),
                                 nn.Linear(256, d))
        self.cls = nn.Parameter(torch.zeros(1, 1, d))
        layer = nn.TransformerEncoderLayer(d, HEADS, 4 * d, dropout, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, LAYERS, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.head = nn.Sequential(nn.Linear(3 * d, 256), nn.GELU(), nn.Dropout(dropout),
                                  nn.Linear(256, k))

    def forward(self, xz, m, vd, hz):
        c = self.ctx(torch.cat([xz, self.model_emb(m), self.vendor_emb(vd)], dim=1))
        t = self.tok(hz) + self.pos_mlp(self.pos) + self.lag_emb.weight
        s = torch.cat([c[:, None] + self.cls, t], dim=1)
        s = self.norm(self.enc(s))
        return self.head(torch.cat([s[:, 0], s[:, 1:].mean(dim=1), s[:, 1]], dim=1))


def build(cfg, dropout):
    return SeqNet(cfg["n_ctx"], cfg["n_hcols"], cfg["lags"], cfg["n_models"], cfg["n_vendors"],
                  cfg["k"], dropout)


def forward(net, prep, Xz, C, Hz, gen=None, train=False):
    x, mx = split_nan(Xz.float())
    h, mh = split_nan(Hz.float())
    m, vd = C[:, 0].long(), C[:, 1].long()
    if train:       # regularise against drive memorisation; prepare for drift
        rnd = lambda t: torch.randn(t.shape, device=t.device, generator=gen)  # noqa: E731
        noise = FEAT_NOISE * rnd(x)
        noise[:, prep.days] = noise[:, prep.days] / FEAT_NOISE * DAYS_NOISE
        x = x + noise * (1 - mx)
        h = h + FEAT_NOISE * rnd(h) * (1 - mh)
        m = torch.where(torch.rand(m.shape, device=m.device, generator=gen) < MODEL_DROP,
                        torch.zeros_like(m), m)
        td = (torch.rand(h.shape[:2], device=h.device, generator=gen) < TOKEN_DROP)
        td[:, 0] = False
        td = td[..., None].float()
        h, mh = h * (1 - td), torch.maximum(mh, td.expand_as(mh))
    return net(torch.cat([x, mx], 1), m, vd, torch.cat([h, mh], 2))


def weighted_bce(logits, Y, W):
    loss = F.binary_cross_entropy_with_logits(logits.float(), Y.float(), reduction="none")
    return (loss * W).sum(), W.sum()


@torch.no_grad()
def stop_logits(net, prep, split, autocast):
    net.eval()
    out = []
    for lo in range(0, len(split), INFER_BATCH):
        sl = slice(lo, lo + INFER_BATCH)
        with autocast:
            out.append(forward(net, prep, split.Xz[sl], split.C[sl], split.H[sl]).float())
    net.train()
    return torch.cat(out)


def loss_of(z, split) -> float:
    s, w = weighted_bce(z, split.Y, split.W)
    return float(s / w.clamp_min(1e-12))


def ap_of(z, split) -> float:
    """Weighted average precision of P(fail within the horizon) on the stop rows."""
    k = split.ap_bins
    p = 1 - torch.prod(1 - torch.sigmoid(z[split.ap_rows, :k].double()), dim=1)
    order = torch.argsort(p, descending=True)
    y, w = split.ap_y[order].double(), split.ap_w[order].double()
    tp, seen = torch.cumsum(w * y, 0), torch.cumsum(w, 0)
    return float((w * y * tp / seen).sum() / (w * y).sum().clamp_min(1e-12))


# ---------------------------------------------------------------- training

class Sampler:
    """Batches of train row indices: shuffled epochs, or drive-balanced draws."""

    def __init__(self, n, balanced_cdf, gen, dev):
        self.n, self.cdf, self.gen, self.dev = n, balanced_cdf, gen, dev
        self.order, self.at = None, n

    def next(self):
        if self.cdf is not None:
            u = torch.rand(BATCH, device=self.dev, generator=self.gen, dtype=torch.float64)
            return torch.searchsorted(self.cdf, u * self.cdf[-1]).clamp_max(self.n - 1)
        if self.at + BATCH > self.n:
            self.order = torch.randperm(self.n, device=self.dev, generator=self.gen)
            self.at = 0
        idx = self.order[self.at:self.at + BATCH]
        self.at += BATCH
        return idx


def optimizer(net, dev):
    decay = [p for n_, p in net.named_parameters() if p.ndim >= 2 and "emb" not in n_]
    other = [p for n_, p in net.named_parameters() if not (p.ndim >= 2 and "emb" not in n_)]
    return torch.optim.AdamW([{"params": decay, "weight_decay": WEIGHT_DECAY},
                              {"params": other, "weight_decay": 0.0}], lr=PEAK_LR,
                             betas=(0.9, 0.98), fused=dev.type == "cuda")


def train_member(i, seconds, cfg, prep, train, stop, base_logit, cdf, autocast, dev):
    """One short cycle. Returns (state dict on CPU, stop logits, stop loss, steps)."""
    gen = torch.Generator(device=dev).manual_seed(SEED + 1000 * i)
    torch.manual_seed(SEED + 1000 * i)
    net = build(cfg, DROPOUTS[i % len(DROPOUTS)]).to(dev)
    with torch.no_grad():
        net.head[-1].bias.copy_(base_logit)
    opt = optimizer(net, dev)
    sampler = Sampler(len(train), cdf if i % 2 == 1 else None, gen, dev)
    start = time.time()
    plan = [start + f * seconds for f in EVAL_FRACTIONS]
    best, best_state, best_z, step, last_eval = float("inf"), None, None, 0, start
    while plan:
        now = time.time()
        frac = min(1.0, (now - start) / seconds)
        lr = PEAK_LR * min(1.0, (step + 1) / WARMUP_STEPS) * (
            0.01 + 0.99 * 0.5 * (1 + math.cos(math.pi * frac)))
        for g_ in opt.param_groups:
            g_["lr"] = lr
        idx = sampler.next()
        with autocast:
            z = forward(net, prep, train.Xz[idx], train.C[idx], train.H[idx], gen, train=True)
        s, w = weighted_bce(z, train.Y[idx], train.W[idx])
        loss = s / w.clamp_min(1e-12)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        step += 1
        now = time.time()
        if now >= plan[0] and (now - last_eval >= MIN_EVAL_GAP or len(plan) == 1):
            while plan and now >= plan[0]:
                plan.pop(0)
            zs = stop_logits(net, prep, stop, autocast)
            v = loss_of(zs, stop)
            last_eval = time.time()
            if best_state is None or v < best:
                best, best_z = v, zs
                best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
            log(f"  member {i} step {step} t {now - start:.0f}s lr {lr:.1e} "
                f"train {float(loss):.4f} stop {v:.4f} ap30 {ap_of(zs, stop):.4f} best {best:.4f}")
    return {k: t.cpu() for k, t in best_state.items()}, best_z, best, step


def save(model_dir, states, cfg, prep):
    torch.save({"states": states}, model_dir / "members.pt.tmp")
    os.replace(model_dir / "members.pt.tmp", model_dir / "members.pt")
    torch.save(prep.state(), model_dir / "stats.pt")
    (model_dir / "config.json").write_text(json.dumps(cfg))


def fit(data, model_dir, deadline, state):
    t0 = time.time()
    dev = device()
    train, stop = state
    torch.set_num_threads(max(1, THREADS))
    n_models, n_vendors = len(data.categorical["model_code"]), len(data.categorical["vendor_code"])
    prep = Prep(data.features, n_models, n_vendors)
    g = torch.Generator(device="cpu").manual_seed(SEED)
    sel = torch.randperm(len(train), generator=g)[:FIT_SAMPLE].to(dev)
    prep.fit(train.F[sel], train.H[sel])
    train.transform(prep)
    stop.transform(prep)
    if dev.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    cfg = {"features": data.features, "lags": data.lags, "k": len(data.bin_edges) - 1,
           "n_ctx": 2 * len(prep.num), "n_hcols": len(data.hist_columns),
           "n_models": n_models, "n_vendors": n_vendors}
    base = (train.Y.float() * train.W).sum(0) / train.W.sum(0).clamp_min(1e-12)
    base_logit = torch.logit(base.clamp(1e-5, 0.5))
    counts = np.bincount(train.drive)
    p = counts[train.drive].astype(np.float64) ** -BALANCE_POWER
    cdf = torch.cumsum(torch.from_numpy(p).to(dev), 0)
    autocast = torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda")

    end = deadline - STOP_MARGIN
    log(f"fit: setup {time.time() - t0:.1f}s, {len(train)} rows, {int(counts.size)} drives, "
        f"{sum(p_.numel() for p_ in build(cfg, 0.1).parameters())} params per member")
    states, zs, ens, tried, steps = [], [], float("inf"), 0, 0
    while True:
        left = end - time.time()
        if left < 0.5 * CYCLE_SECONDS and tried > 0:
            break
        members_left = max(1, round(left / CYCLE_SECONDS))
        seconds = left / members_left
        t = time.time()
        sd, z, v, k = train_member(tried, seconds, cfg, prep, train, stop, base_logit, cdf,
                                   autocast, dev)
        steps += k
        cand = torch.stack(zs + [z]).mean(0)
        v_ens = loss_of(cand, stop)
        accepted = v_ens < ens - 1e-6 or not states
        log(f"member {tried}: {k} steps, {time.time() - t:.0f}s, stop {v:.4f}; ensemble of "
            f"{len(states) + 1} would give {v_ens:.4f} (ap30 {ap_of(cand, stop):.4f}) vs "
            f"{ens:.4f}: {'kept' if accepted else 'dropped'}")
        if accepted:
            states.append(sd)
            zs.append(z)
            ens = v_ens
            save(model_dir, states, cfg, prep)
        tried += 1
    peak = f", peak gpu {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB" if dev.type == "cuda" else ""
    log(f"done: {tried} members tried, {len(states)} kept, {steps} steps, ensemble stop "
        f"{ens:.4f}{peak}")


# ---------------------------------------------------------------- inference

class Loaded:
    def __init__(self, nets, prep, dev):
        self.nets, self.prep, self.dev = nets, prep, dev


def load(model_dir):
    dev = device()
    cfg = json.loads((model_dir / "config.json").read_text())
    prep = Prep(cfg["features"], cfg["n_models"], cfg["n_vendors"])
    prep.set_state(torch.load(model_dir / "stats.pt"), dev)
    nets = []
    for sd in torch.load(model_dir / "members.pt")["states"]:
        net = build(cfg, 0.0)
        net.load_state_dict(sd)
        nets.append(net.to(dev).eval())
    return Loaded(nets, prep, dev)


@torch.no_grad()
def predict(model, X, hist):
    """Each row is scored from its own X and hist: features are per-row, nets are in eval
    mode, and the members' logits are averaged."""
    dev, prep = model.dev, model.prep
    Fm = make_features(np.asarray(X, dtype=np.float32), np.asarray(hist, dtype=np.float16))
    autocast = torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda")
    out = []
    for lo in range(0, len(Fm), INFER_BATCH):
        f = torch.from_numpy(np.ascontiguousarray(Fm[lo:lo + INFER_BATCH])).to(dev)
        h = torch.from_numpy(np.ascontiguousarray(hist[lo:lo + INFER_BATCH], dtype=np.float16)).to(dev)
        xz, c, hz = prep.feat(f), prep.cats(f), prep.hist(h)
        with autocast:
            z = torch.stack([forward(net, prep, xz, c, hz).float() for net in model.nets]).mean(0)
        out.append(z.cpu().numpy())
    z = np.concatenate(out)
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=30.0, neginf=-30.0), -30.0, 30.0)

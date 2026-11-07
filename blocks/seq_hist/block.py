"""seq_hist: read each drive's SMART history as a sequence over the lag axis.

One forward pass gives 7 hazard logits per row. The 19 lags (0..365 days back) are tokens:
values, deltas to the current reading and NaN masks go in as channels, and the lag position
(log lag, log gap to the next lag, a learned index embedding) tells the transformer how the
tokens are spaced. A context token built from X (days in service, capacity, model and vendor
embeddings, all other features) joins the sequence, and the pooled output feeds the head.

Loss: masked per-bin binary cross-entropy that follows survival.expand (at-risk bins, event
bin, actuarial exposure for censored rows), weighted by weight ** 0.5. Train and stop data
live on the GPU. The best weights by stop loss (EMA of the weights) are saved as they appear.
"""

from __future__ import annotations

import json
import math
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from survival import expand

SEED = 42
WEIGHT_POWER = 0.5
D_MODEL = 96
HEADS = 4
LAYERS = 3
DROPOUT = 0.3
FEAT_NOISE = 0.15           # gaussian jitter on standardised inputs, training only
TOKEN_DROP = 0.1            # P(a lag token is blanked to "missing"), training only
# the 1.5 GiB smoke cap cannot hold 4096-row activations; the full run (13.5 GiB) can
SMALL_GPU = float(os.environ.get("HDA_VRAM_GIB", 99)) < 4
BATCH = 1024 if SMALL_GPU else 4096
PEAK_LR = 3e-4
WEIGHT_DECAY = 0.05
WARMUP_STEPS = 300
EMA_DECAY = 0.999
MODEL_DROP = 0.15           # P(model_code replaced by "unknown") while training, for drift
EVAL_EVERY = 400 if not SMALL_GPU else 250   # steps
STOP_MARGIN = 25            # seconds kept for the last evaluation and the save
INFER_BATCH = 2048 if SMALL_GPU else 8192
CLIP = 8.0
LOG_COLS = ("_raw", "_d7", "_d30")


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ---------------------------------------------------------------- data on the GPU

def to_device(arr: np.ndarray, dev, dtype, chunk: int = 1 << 18) -> torch.Tensor:
    """Memory-mapped array to a device tensor, one chunk at a time (bounded RAM)."""
    out = torch.empty(arr.shape, dtype=dtype, device=dev)
    for lo in range(0, len(arr), chunk):
        out[lo:lo + chunk] = torch.from_numpy(np.array(arr[lo:lo + chunk])).to(dev)
    return out


def targets(meta, edges, dev):
    """Per-row (n, K) label and loss weight following survival.expand. Weight is zero in
    bins where the row is not at risk. Censored rows carry their actuarial exposure."""
    d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, w_rows = expand(d, e, w, edges)
    # weight ** power on the sampling weight only; exposure (a fraction) stays linear
    exposure = w_rows / np.asarray(w, dtype=np.float64)[idx]
    w_rows = np.asarray(w, dtype=np.float64)[idx] ** WEIGHT_POWER * exposure
    Y = torch.zeros(len(meta), len(edges) - 1, dtype=torch.int8)
    W = torch.zeros(len(meta), len(edges) - 1, dtype=torch.float32)
    idx_t, bins_t = torch.from_numpy(idx), torch.from_numpy(bins.astype(np.int64))
    Y[idx_t, bins_t] = torch.from_numpy(y)
    W[idx_t, bins_t] = torch.from_numpy(w_rows.astype(np.float32))
    return Y.to(dev), W.to(dev)


class Split:
    def __init__(self, part, edges, dev):
        self.X = to_device(part.X, dev, torch.float32)
        self.H = to_device(part.hist, dev, torch.float16)
        self.Y, self.W = targets(part.meta, edges, dev)

    def __len__(self):
        return self.X.shape[0]


def prepare(data, model_dir):
    dev = device()
    edges = data.bin_edges
    train = Split(data.train, edges, dev)
    stop = Split(data.stop, edges, dev)
    print(f"prepared: train {len(train)} rows, stop {len(stop)} rows, "
          f"gpu {torch.cuda.memory_allocated() / 2**30:.2f} GiB" if dev.type == "cuda"
          else "prepared on cpu", flush=True)
    return train, stop


# ---------------------------------------------------------------- feature transform

class Norm:
    """Fixed input transform: signed log1p for count-like columns, then standardise with
    statistics from the training rows. Missing becomes 0 plus a mask channel."""

    def __init__(self, features, categorical, x_mu, x_sd, h_mu, h_sd, n_models, n_vendors):
        self.features = list(features)
        self.cat = [self.features.index(c) for c in ("model_code", "vendor_code")]
        self.num = [i for i in range(len(self.features)) if i not in self.cat]
        self.log = [j for j, i in enumerate(self.num)
                    if self.features[i].endswith(LOG_COLS) or self.features[i] == "days_in_service"]
        self.x_mu, self.x_sd, self.h_mu, self.h_sd = x_mu, x_sd, h_mu, h_sd
        self.n_models, self.n_vendors = n_models, n_vendors

    def x_raw(self, X):
        """(n, features) float32 -> transformed numeric part, before standardising."""
        v = X[:, self.num]
        if self.log:
            t = v[:, self.log]
            v = v.clone()
            v[:, self.log] = torch.sign(t) * torch.log1p(torch.abs(t))
        return v

    def x(self, X):
        v = self.x_raw(X)
        miss = torch.isnan(v) | torch.isinf(v)
        z = ((torch.where(miss, torch.zeros_like(v), v) - self.x_mu) / self.x_sd).clamp(-CLIP, CLIP)
        z = torch.where(miss, torch.zeros_like(z), z)
        cats = X[:, self.cat]
        cats = torch.nan_to_num(cats, nan=-1.0)
        m = cats[:, 0].long().clamp(-1, self.n_models) + 1          # 0 = unknown
        m = torch.where(m > self.n_models, torch.zeros_like(m), m)
        vd = cats[:, 1].long().clamp(-1, self.n_vendors) + 1
        vd = torch.where(vd > self.n_vendors, torch.zeros_like(vd), vd)
        return torch.cat([z, miss.float()], dim=1), m, vd

    def h(self, H):
        """(n, lags, cols) float16 -> (n, lags, 3 * cols) float32: values, deltas, masks."""
        h = H.float()
        miss = torch.isnan(h) | torch.isinf(h)
        z = ((torch.where(miss, torch.zeros_like(h), h) - self.h_mu) / self.h_sd).clamp(-CLIP, CLIP)
        z = torch.where(miss, torch.zeros_like(z), z)
        both = (~miss) & (~miss[:, :1])
        delta = torch.where(both, z - z[:, :1], torch.zeros_like(z)).clamp(-CLIP, CLIP)
        return torch.cat([z, delta, miss.float()], dim=2)


def fit_norm(data, train, dev, n_models, n_vendors) -> Norm:
    """Statistics from a fixed random subsample of the training rows."""
    g = torch.Generator(device="cpu").manual_seed(SEED)
    n = min(len(train), 200_000)
    sel = torch.randperm(len(train), generator=g)[:n].to(dev)
    norm = Norm(data.features, data.categorical, None, None, None, None, n_models, n_vendors)
    v = norm.x_raw(train.X[sel])
    v = torch.where(torch.isfinite(v), v, torch.full_like(v, float("nan")))
    mu = torch.nanmean(v, dim=0)
    var = torch.nanmean((v - mu) ** 2, dim=0)
    norm.x_mu = torch.nan_to_num(mu)
    norm.x_sd = torch.nan_to_num(var.sqrt(), nan=1.0).clamp_min(1e-3)
    h = train.H[sel].float()
    h = torch.where(torch.isfinite(h), h, torch.full_like(h, float("nan")))
    hm = torch.nanmean(h, dim=(0, 1))
    hv = torch.nanmean((h - hm) ** 2, dim=(0, 1))
    norm.h_mu = torch.nan_to_num(hm)
    norm.h_sd = torch.nan_to_num(hv.sqrt(), nan=1.0).clamp_min(1e-3)
    return norm


# ---------------------------------------------------------------- the network

class SeqNet(nn.Module):
    def __init__(self, n_x, n_hcols, lags, n_models, n_vendors, edges_k):
        super().__init__()
        d = D_MODEL
        lags = np.asarray(lags, dtype=np.float32)
        gap = np.diff(lags, append=lags[-1] + (lags[-1] - lags[-2]))
        pos = np.stack([np.log1p(lags), np.log1p(gap), lags / lags.max()], axis=1)
        self.register_buffer("pos", torch.from_numpy(pos.astype(np.float32)), persistent=False)
        self.n_lags = len(lags)
        self.tok = nn.Linear(3 * n_hcols, d)
        self.pos_mlp = nn.Sequential(nn.Linear(3, d), nn.GELU(), nn.Linear(d, d))
        self.lag_emb = nn.Embedding(len(lags), d)
        self.model_emb = nn.Embedding(n_models + 1, 16)
        self.vendor_emb = nn.Embedding(n_vendors + 1, 4)
        self.ctx = nn.Sequential(nn.Linear(n_x + 20, 256), nn.GELU(), nn.Dropout(DROPOUT),
                                 nn.Linear(256, d))
        self.cls = nn.Parameter(torch.zeros(1, 1, d))
        layer = nn.TransformerEncoderLayer(d, HEADS, 4 * d, DROPOUT, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, LAYERS, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.head = nn.Sequential(nn.Linear(3 * d, 256), nn.GELU(), nn.Dropout(DROPOUT),
                                  nn.Linear(256, edges_k))

    def forward(self, xz, m, vd, hz):
        c = self.ctx(torch.cat([xz, self.model_emb(m), self.vendor_emb(vd)], dim=1))
        t = self.tok(hz) + self.pos_mlp(self.pos) + self.lag_emb.weight
        s = torch.cat([c[:, None] + self.cls, t], dim=1)
        s = self.norm(self.enc(s))
        pooled = torch.cat([s[:, 0], s[:, 1:].mean(dim=1), s[:, 1]], dim=1)
        return self.head(pooled)


def build(cfg):
    return SeqNet(cfg["n_x"], cfg["n_hcols"], cfg["lags"], cfg["n_models"], cfg["n_vendors"],
                  cfg["k"])


def forward(net, norm, X, H, model_drop=0.0, gen=None):
    xz, m, vd = norm.x(X)
    hz = norm.h(H)
    if model_drop > 0:      # training only: regularise against drive memorisation, prepare for drift
        nx, nh = len(norm.num), hz.shape[2] // 3
        rnd = lambda t: torch.randn(t.shape, device=t.device, generator=gen)  # noqa: E731
        xz = torch.cat([xz[:, :nx] + FEAT_NOISE * rnd(xz[:, :nx]) * (1 - xz[:, nx:]), xz[:, nx:]], 1)
        live = 1 - hz[..., 2 * nh:]
        hz = torch.cat([hz[..., :2 * nh] + FEAT_NOISE * rnd(hz[..., :2 * nh]) * live.repeat(1, 1, 2),
                        hz[..., 2 * nh:]], 2)
        drop = torch.rand(m.shape, device=m.device, generator=gen) < model_drop
        m = torch.where(drop, torch.zeros_like(m), m)
        tdrop = torch.rand(hz.shape[:2], device=m.device, generator=gen) < TOKEN_DROP
        tdrop[:, 0] = False
        tdrop = tdrop[..., None].float()
        hz = torch.cat([hz[..., :2 * nh] * (1 - tdrop), torch.maximum(hz[..., 2 * nh:], tdrop.expand(-1, -1, nh))], 2)
    return net(xz, m, vd, hz)


def weighted_bce(logits, Y, W):
    loss = F.binary_cross_entropy_with_logits(logits.float(), Y.float(), reduction="none")
    return (loss * W).sum(), W.sum()


@torch.no_grad()
def stop_loss(net, norm, split, autocast) -> float:
    net.eval()
    total, wsum = 0.0, 0.0
    for lo in range(0, len(split), INFER_BATCH):
        sl = slice(lo, lo + INFER_BATCH)
        with autocast:
            z = forward(net, norm, split.X[sl], split.H[sl])
        s, w = weighted_bce(z, split.Y[sl], split.W[sl])
        total += float(s)
        wsum += float(w)
    net.train()
    return total / max(wsum, 1e-12)


def save(model_dir, ema, cfg, norm, tag="best"):
    torch.save({"state": {k: v.detach().cpu() for k, v in ema.state_dict().items()}},
               model_dir / f"{tag}.pt.tmp")
    os.replace(model_dir / f"{tag}.pt.tmp", model_dir / f"{tag}.pt")
    stats = {"x_mu": norm.x_mu, "x_sd": norm.x_sd, "h_mu": norm.h_mu, "h_sd": norm.h_sd}
    torch.save({k: v.cpu() for k, v in stats.items()}, model_dir / "stats.pt")
    (model_dir / "config.json").write_text(json.dumps(cfg))


def fit(data, model_dir, deadline, state):
    t0 = time.time()
    dev = device()
    train, stop = state
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    gen = torch.Generator(device=dev).manual_seed(SEED)
    n_models = len(data.categorical["model_code"])
    n_vendors = len(data.categorical["vendor_code"])
    norm = fit_norm(data, train, dev, n_models, n_vendors)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()    # report the training peak, not the statistics pass
    cfg = {"features": data.features, "lags": data.lags, "k": len(data.bin_edges) - 1,
           "n_x": 2 * len(norm.num), "n_hcols": len(data.hist_columns),
           "n_models": n_models, "n_vendors": n_vendors, "log_cols": list(LOG_COLS)}
    net = build(cfg).to(dev)
    ema = build(cfg).to(dev)
    ema.load_state_dict(net.state_dict())
    ema.eval()
    for p in ema.parameters():
        p.requires_grad_(False)

    # start each bin's logit at its weighted base rate
    base = (train.Y.float() * train.W).sum(0) / train.W.sum(0).clamp_min(1e-12)
    with torch.no_grad():
        net.head[-1].bias.copy_(torch.logit(base.clamp(1e-5, 0.5)))
        ema.head[-1].bias.copy_(net.head[-1].bias)

    decay = [p for n_, p in net.named_parameters() if p.ndim >= 2 and "emb" not in n_]
    other = [p for n_, p in net.named_parameters() if not (p.ndim >= 2 and "emb" not in n_)]
    opt = torch.optim.AdamW([{"params": decay, "weight_decay": WEIGHT_DECAY},
                             {"params": other, "weight_decay": 0.0}], lr=PEAK_LR,
                            betas=(0.9, 0.98), fused=dev.type == "cuda")
    autocast = torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda")

    end = deadline - STOP_MARGIN
    t_start = time.time()
    total_time = max(end - t_start, 1.0)
    n = len(train)
    best, best_step, step, epoch = float("inf"), 0, 0, 0
    done = False
    print(f"fit: setup {t_start - t0:.1f}s, {n} rows, params "
          f"{sum(p.numel() for p in net.parameters())}", flush=True)
    while not done:
        order = torch.randperm(n, device=dev, generator=gen)
        for lo in range(0, n - BATCH + 1, BATCH):
            now = time.time()
            if now >= end:
                done = True
                break
            frac = (now - t_start) / total_time
            lr = PEAK_LR * min(1.0, (step + 1) / WARMUP_STEPS) * (
                0.02 + 0.98 * 0.5 * (1 + math.cos(math.pi * frac)))
            for g_ in opt.param_groups:
                g_["lr"] = lr
            idx = order[lo:lo + BATCH]
            with autocast:
                z = forward(net, norm, train.X[idx], train.H[idx], MODEL_DROP, gen)
            s, w = weighted_bce(z, train.Y[idx], train.W[idx])
            loss = s / w.clamp_min(1e-12)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            step += 1
            with torch.no_grad():
                d = min(EMA_DECAY, (1 + step) / (10 + step))
                for pe, pn in zip(ema.parameters(), net.parameters()):
                    pe.lerp_(pn, 1 - d)
                for be, bn in zip(ema.buffers(), net.buffers()):
                    be.copy_(bn)
            if step % EVAL_EVERY == 0:
                v = stop_loss(ema, norm, stop, autocast)
                if v < best:
                    best, best_step = v, step
                    save(model_dir, ema, cfg, norm)
                print(f"step {step} epoch {epoch} t {time.time() - t_start:.0f}s lr {lr:.2e} "
                      f"train {float(loss):.4f} stop {v:.4f} best {best:.4f}@{best_step}",
                      flush=True)
        epoch += 1
    v = stop_loss(ema, norm, stop, autocast)
    if v < best or not (model_dir / "best.pt").exists():
        best, best_step = v, step
        save(model_dir, ema, cfg, norm)
    print(f"done: {step} steps, {epoch} epochs, final stop {v:.4f}, best {best:.4f}@{best_step}, "
          f"peak gpu {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB"
          if dev.type == "cuda" else f"done: {step} steps, best {best:.4f}", flush=True)


# ---------------------------------------------------------------- inference

class Loaded:
    def __init__(self, net, norm, dev):
        self.net, self.norm, self.dev = net, norm, dev


def load(model_dir):
    dev = device()
    cfg = json.loads((model_dir / "config.json").read_text())
    net = build(cfg)
    net.load_state_dict(torch.load(model_dir / "best.pt")["state"])
    net.to(dev).eval()
    s = {k: v.to(dev) for k, v in torch.load(model_dir / "stats.pt").items()}
    norm = Norm(cfg["features"], None, s["x_mu"], s["x_sd"], s["h_mu"], s["h_sd"],
                cfg["n_models"], cfg["n_vendors"])
    return Loaded(net, norm, dev)


@torch.no_grad()
def predict(model, X, hist):
    autocast = torch.autocast(model.dev.type, dtype=torch.bfloat16,
                              enabled=model.dev.type == "cuda")
    out = []
    for lo in range(0, len(X), INFER_BATCH):
        xb = torch.from_numpy(np.ascontiguousarray(X[lo:lo + INFER_BATCH], dtype=np.float32))
        hb = torch.from_numpy(np.ascontiguousarray(hist[lo:lo + INFER_BATCH], dtype=np.float16))
        with autocast:
            z = forward(model.net, model.norm, xb.to(model.dev), hb.to(model.dev))
        out.append(z.float().cpu().numpy())
    z = np.concatenate(out)
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=30.0, neginf=-30.0), -30.0, 30.0)

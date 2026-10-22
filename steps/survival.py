"""Discrete-time survival math: person-period expansion, survival curves, life estimates.

Conventions (shared with the snapshot labels):
- duration d = days from the snapshot to the event or censoring day.
- event at d: the drive's failure day is d days after the snapshot (Backblaze marks the
  last operational day with failure = 1).
- censored at d: the drive is known to be alive through day d, unknown after.
- bin k covers days [edges[k], edges[k+1]). "Fails within H days" means failure on a
  day < H, so P(fail within H) = 1 - S(H) where S(H) = prod over bins below H of (1 - h_k).
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np


def expand(duration: np.ndarray, event: np.ndarray, weight: np.ndarray,
           edges: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Person-period rows: (snapshot index, bin index, label, weight).

    A snapshot contributes a row for every bin it is at risk in (d >= bin start). The
    label is 1 only in the bin that holds the failure. A censored snapshot whose
    observation ends inside a bin contributes that bin with weight scaled by the
    observed fraction of the bin (actuarial adjustment). Dropping it would bias the hazard
    upward, and counting it as fully survived would bias it downward.
    """
    duration = np.asarray(duration, dtype=np.int64)
    event = np.asarray(event, dtype=bool)
    weight = np.asarray(weight, dtype=np.float64)
    if (duration < 0).any():
        raise ValueError("negative duration")
    idx, bins, labels, weights = [], [], [], []
    for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        at_risk = np.flatnonzero(duration >= a)
        d, e = duration[at_risk], event[at_risk]
        failed_here = e & (d < b)
        # censored inside the bin: alive through day d, so (d - a + 1) of (b - a) days seen
        exposure = np.where(~e & (d < b - 1), (d - a + 1) / (b - a), 1.0)
        idx.append(at_risk)
        bins.append(np.full(at_risk.size, k, dtype=np.int16))
        labels.append(failed_here.astype(np.int8))
        weights.append(weight[at_risk] * exposure)
    return (np.concatenate(idx), np.concatenate(bins), np.concatenate(labels),
            np.concatenate(weights))


def known_status(duration: np.ndarray, event: np.ndarray, horizon: int) -> np.ndarray:
    """1 = failed within horizon, 0 = known alive through day horizon-1, -1 = unknown."""
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    out = np.full(duration.shape, -1, dtype=np.int8)
    out[event & (duration < horizon)] = 1
    out[(event & (duration >= horizon)) | (~event & (duration >= horizon - 1))] = 0
    return out


class ExpandedSequence(lgb.Sequence):
    """Feeds expanded rows X[idx] + bin start to LightGBM in batches.

    The expanded matrix is never materialised (it is several times the snapshot matrix).
    """

    def __init__(self, X: np.ndarray, idx: np.ndarray, bin_start: np.ndarray,
                 batch_size: int = 1 << 16):
        self.X, self.idx, self.bin_start = X, idx, bin_start.astype(np.float32)
        self.batch_size = batch_size

    def __len__(self) -> int:
        return self.idx.size

    def __getitem__(self, key):
        # LightGBM wants float64; converting one batch at a time keeps memory bounded
        if isinstance(key, (int, np.integer)):
            return np.append(self.X[self.idx[key]], self.bin_start[key]).astype(np.float64)
        rows = self.X[self.idx[key]].astype(np.float64)
        return np.hstack([rows, self.bin_start[key][:, None]])


def hazards_to_survival(h: np.ndarray) -> np.ndarray:
    """S at each bin end edge, shape (n, K): S[:, k] = prod_{j<=k} (1 - h_j)."""
    return np.cumprod(1.0 - np.clip(h, 0.0, 1.0), axis=1)


def failure_probability(S: np.ndarray, edges: list[int], horizon: int) -> np.ndarray:
    """P(fail within horizon days); horizon must be a bin edge."""
    k = edges.index(horizon)
    return 1.0 - S[:, k - 1] if k > 0 else np.zeros(S.shape[0])


def life_quantile(S: np.ndarray, edges: list[int], q: float) -> np.ndarray:
    """Days until the failure probability reaches q (linear inside a bin), inf if beyond.

    q = 0.5 gives the median remaining life. Inf means "more than edges[-1] days".
    """
    n, K = S.shape
    full = np.hstack([np.ones((n, 1)), S])            # S at every edge, including day 0
    target = 1.0 - q
    below = full <= target
    has = below.any(axis=1)
    k = np.where(has, below.argmax(axis=1), K)        # first edge with S <= target
    out = np.full(n, np.inf)
    rows = np.flatnonzero(has)
    kk = k[rows]
    s_hi, s_lo = full[rows, kk - 1], full[rows, kk]   # S falls from s_hi to s_lo in bin kk-1
    a = np.asarray(edges)[kk - 1]
    b = np.asarray(edges)[kk]
    frac = np.where(s_hi > s_lo, (s_hi - target) / np.maximum(s_hi - s_lo, 1e-12), 0.0)
    out[rows] = a + frac * (b - a)
    return out


def restricted_mean_life(S: np.ndarray, edges: list[int]) -> np.ndarray:
    """Expected days alive within the next edges[-1] days (area under linear S)."""
    full = np.hstack([np.ones((S.shape[0], 1)), S])
    widths = np.diff(np.asarray(edges, dtype=float))
    return ((full[:, :-1] + full[:, 1:]) / 2 * widths).sum(axis=1)

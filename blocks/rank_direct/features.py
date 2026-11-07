"""Engineered features from `hist` (19 lags x 20 SMART columns, signed log1p, NaN if absent).

One pure function of (X, hist), shared by prepare and predict. Every row is computed on its
own: no statistic crosses rows. Differences are taken in log space (ratios of counters, so
they do not depend on drive size) or on rates per day.
"""

from __future__ import annotations

import warnings

import numpy as np

LAGS = [0, 1, 2, 3, 4, 5, 6, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365]
HIST_COLUMNS = ['smart_1_normalized', 'smart_3_normalized', 'smart_4_raw', 'smart_5_raw',
                'smart_7_normalized', 'smart_9_raw', 'smart_10_raw', 'smart_183_raw',
                'smart_184_raw', 'smart_187_raw', 'smart_189_raw', 'smart_190_raw',
                'smart_192_raw', 'smart_193_raw', 'smart_194_raw', 'smart_197_raw',
                'smart_198_raw', 'smart_199_raw', 'smart_241_raw', 'smart_242_raw']
C = {n.replace("smart_", "s").replace("_raw", "").replace("_normalized", "n"): i
     for i, n in enumerate(HIST_COLUMNS)}          # s5, s187, s1n, ...
LI = {lag: j for j, lag in enumerate(LAGS)}

MAIN = ["s5", "s187", "s197", "s198"]               # counters with a full window family
MINOR = ["s183", "s189"]                            # mostly Seagate-only: long windows
CRITICAL = MAIN + MINOR + ["s199"]
WINDOWS_MAIN = (14, 60, 90, 180, 365)
WINDOWS_MINOR = (90, 365)
SINCE = ["s5", "s187", "s197", "s198", "s183", "s189"]
CHUNK = 20_000

warnings.filterwarnings("ignore", category=RuntimeWarning)


def _slog(x):
    return np.sign(x) * np.log1p(np.abs(x))


def _raw(v):
    """Undo signed log1p."""
    return np.sign(v) * np.expm1(np.abs(v))


def _rate(raw, name, lag):
    """Counter increase per day over the last `lag` days, from lag 0 to lag `lag`."""
    return (raw[name][:, 0] - raw[name][:, LI[lag]]) / lag


def _names():
    names = []
    for c in MAIN:
        names += [f"{c}_dl{w}" for w in WINDOWS_MAIN]
    for c in MINOR:
        names += [f"{c}_dl{w}" for w in WINDOWS_MINOR]
    names += [f"{c}_accel" for c in ("s5", "s187", "s197", "s198")]
    names += [f"{c}_since_move" for c in SINCE]
    names += ["max_jump", "burden_365", "n_moved_7", "n_moved_30", "n_moved_90",
              "n_moved_365", "n_nonzero"]
    names += ["t194_std", "t194_dev", "t194_std30", "t190_std"]
    for c in ("s7n", "s1n", "s3n"):
        names += [f"{c}_std"]
    names += ["s7n_dev", "s1n_dev"]
    names += [f"{c}_per_age" for c in ("s5", "s187", "s197", "s198")]
    names += ["startstop_rate90"]
    return names


NAMES = _names()


def _block(hist):
    v = hist.astype(np.float32)                     # (n, 19, 20) signed log1p
    n = v.shape[0]
    col = {k: v[:, :, i] for k, i in C.items()}     # (n, 19) each
    raw = {k: _raw(col[k]) for k in
           ("s5", "s183", "s187", "s189", "s197", "s198", "s199", "s9", "s4")}
    out = []

    # log-ratio growth over longer windows
    for c in MAIN:
        for w in WINDOWS_MAIN:
            out.append(col[c][:, 0] - col[c][:, LI[w]])
    for c in MINOR:
        for w in WINDOWS_MINOR:
            out.append(col[c][:, 0] - col[c][:, LI[w]])

    # acceleration: recent increase per day against the older one
    for c in ("s5", "s187", "s197", "s198"):
        recent = _rate(raw, c, 30)
        old = (raw[c][:, LI[30]] - raw[c][:, LI[365]]) / 335.0
        out.append(_slog(recent * 30) - _slog(old * 30))

    # days since the counter last moved: first lag at which it differs from lag 0
    for c in SINCE:
        x = col[c]
        differs = np.nan_to_num(np.abs(x - x[:, :1]), nan=0.0) > 1e-6
        first = differs.argmax(axis=1)
        last_valid = len(LAGS) - 1 - (~np.isnan(x))[:, ::-1].argmax(axis=1)
        # never moved: unmoved at least as far back as the oldest lag the drive has
        since = np.asarray(LAGS)[np.where(differs.any(axis=1), first, last_valid)]
        out.append(np.where(np.isnan(x[:, 0]), np.nan, since).astype(np.float32))

    # largest jump between neighbouring lags, over the critical counters
    jumps = np.stack([np.abs(np.diff(col[c], axis=1)) for c in CRITICAL], axis=2)
    out.append(np.nanmax(jumps.reshape(n, -1), axis=1))
    d365 = np.stack([col[c][:, 0] - col[c][:, LI[365]] for c in CRITICAL], axis=1)
    out.append(np.nansum(d365, axis=1))
    for w in (7, 30, 90, 365):
        moved = np.stack([col[c][:, 0] != col[c][:, LI[w]] for c in CRITICAL], axis=1)
        valid = np.stack([~np.isnan(col[c][:, LI[w]]) & ~np.isnan(col[c][:, 0])
                          for c in CRITICAL], axis=1)
        out.append((moved & valid).sum(axis=1).astype(np.float32))
    out.append(np.nan_to_num(np.stack([col[c][:, 0] for c in CRITICAL], axis=1) > 0)
               .sum(axis=1).astype(np.float32))

    # temperature volatility (spread and deviation, not the level)
    t194 = np.expm1(col["s194"])
    out.append(np.nanstd(t194, axis=1))
    out.append(t194[:, 0] - np.nanmean(t194, axis=1))
    out.append(np.nanstd(t194[:, :LI[30] + 1], axis=1))
    out.append(np.nanstd(np.expm1(col["s190"]), axis=1))

    # seek / read / spin-up normalized values: how unstable, how far from usual
    for c in ("s7n", "s1n", "s3n"):
        out.append(np.nanstd(col[c], axis=1))
    for c in ("s7n", "s1n"):
        out.append(col[c][:, 0] - np.nanmean(col[c], axis=1))

    # relative to the drive's age
    log_age = np.log1p(np.maximum(raw["s9"][:, 0] / 24.0, 0))
    for c in ("s5", "s187", "s197", "s198"):
        out.append(col[c][:, 0] - log_age)
    out.append(_rate(raw, "s4", 90))

    F = np.stack(out, axis=1).astype(np.float32)
    F[~np.isfinite(F)] = np.nan
    return F


def make_features(X, hist):
    """(n, 65) float32 + (n, 19, 20) float16 -> (n, 65 + len(NAMES)) float32."""
    assert hist.shape[1:] == (len(LAGS), len(HIST_COLUMNS)), hist.shape
    new = np.empty((X.shape[0], len(NAMES)), dtype=np.float32)
    for lo in range(0, X.shape[0], CHUNK):
        new[lo:lo + CHUNK] = _block(np.asarray(hist[lo:lo + CHUNK]))
    return np.hstack([np.asarray(X, dtype=np.float32), new])

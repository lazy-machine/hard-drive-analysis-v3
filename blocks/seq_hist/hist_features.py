"""Engineered features from `hist` (19 lags x 20 SMART columns, signed log1p, NaN if absent).

One pure function of (X, hist), shared by prepare and predict. Every row is computed on its
own: no statistic crosses rows. Differences are taken in log space (ratios of counters, so
they do not depend on drive size) or on rates per day.

Features come in families, so a family can be switched off for an ablation (see FAMILIES).
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
LAG_ARR = np.asarray(LAGS, dtype=np.float32)

MAIN = ["s5", "s187", "s197", "s198"]               # counters with a full window family
MINOR = ["s183", "s189"]                            # mostly Seagate-only: long windows
CRITICAL = MAIN + MINOR + ["s199"]
SINCE = MAIN + MINOR
WINDOWS_MAIN = (14, 60, 90, 180, 365)
WINDOWS_MINOR = (90, 365)
SLOPE_SPANS = (90, 365)
NORMALIZED = ("s1n", "s3n", "s7n")
CHUNK = 20_000

warnings.filterwarnings("ignore", category=RuntimeWarning)


def _slog(x):
    return np.sign(x) * np.log1p(np.abs(x))


def _raw(v):
    """Undo signed log1p."""
    return np.sign(v) * np.expm1(np.abs(v))


def _slope(y, span):
    """Least-squares slope of y against days-ago over lags up to `span`, per row, sign
    flipped so a counter that grows toward now has a positive slope. NaN if < 3 points."""
    k = LI[span] + 1
    x = np.broadcast_to(LAG_ARR[:k], (y.shape[0], k))
    y = y[:, :k]
    ok = ~np.isnan(y)
    cnt = ok.sum(axis=1)
    xm = np.where(ok, x, 0).sum(axis=1) / np.maximum(cnt, 1)
    ym = np.where(ok, y, 0).sum(axis=1) / np.maximum(cnt, 1)
    dx = np.where(ok, x - xm[:, None], 0)
    cov = (dx * np.where(ok, y - ym[:, None], 0)).sum(axis=1)
    var = (dx * dx).sum(axis=1)
    return np.where(cnt >= 3, -cov / np.maximum(var, 1e-9), np.nan)


def _families(hist):
    """Yield (family, [(name, column), ...]) for one chunk."""
    v = hist.astype(np.float32)                     # (n, 19, 20) signed log1p
    n = v.shape[0]
    col = {k: v[:, :, i] for k, i in C.items()}     # (n, 19) each
    raw = {k: _raw(col[k]) for k in
           ("s5", "s183", "s187", "s189", "s197", "s198", "s199", "s9", "s4")}

    yield "growth", ([(f"{c}_dl{w}", col[c][:, 0] - col[c][:, LI[w]])
                      for c in MAIN for w in WINDOWS_MAIN]
                     + [(f"{c}_dl{w}", col[c][:, 0] - col[c][:, LI[w]])
                        for c in MINOR for w in WINDOWS_MINOR])

    # acceleration: recent increase per day against the older one
    acc = []
    for c in MAIN:
        recent = (raw[c][:, 0] - raw[c][:, LI[30]]) / 30.0
        old = (raw[c][:, LI[30]] - raw[c][:, LI[365]]) / 335.0
        acc.append((f"{c}_accel", _slog(recent * 30) - _slog(old * 30)))
    yield "accel", acc

    # days since the counter last moved: first lag at which it differs from lag 0
    since = []
    for c in SINCE:
        x = col[c]
        differs = np.nan_to_num(np.abs(x - x[:, :1]), nan=0.0) > 1e-6
        first = differs.argmax(axis=1)
        last_valid = len(LAGS) - 1 - (~np.isnan(x))[:, ::-1].argmax(axis=1)
        # never moved: unmoved at least as far back as the oldest lag the drive has
        s = LAG_ARR[np.where(differs.any(axis=1), first, last_valid)]
        since.append((f"{c}_since_move", np.where(np.isnan(x[:, 0]), np.nan, s)))
    yield "since_move", since

    # pooled over the critical counters
    agg = []
    jumps = np.stack([np.abs(np.diff(col[c], axis=1)) for c in CRITICAL], axis=2)
    agg.append(("max_jump", np.nanmax(jumps.reshape(n, -1), axis=1)))
    d365 = np.stack([col[c][:, 0] - col[c][:, LI[365]] for c in CRITICAL], axis=1)
    agg.append(("burden_365", np.nansum(d365, axis=1)))
    for w in (7, 30, 90, 365):
        moved = np.stack([col[c][:, 0] != col[c][:, LI[w]] for c in CRITICAL], axis=1)
        valid = np.stack([~np.isnan(col[c][:, LI[w]]) & ~np.isnan(col[c][:, 0])
                          for c in CRITICAL], axis=1)
        agg.append((f"n_moved_{w}", (moved & valid).sum(axis=1)))
    agg.append(("n_nonzero", np.nan_to_num(
        np.stack([col[c][:, 0] for c in CRITICAL], axis=1) > 0).sum(axis=1)))
    yield "pooled", agg

    # temperature volatility (spread and deviation, not the level)
    t194 = np.expm1(col["s194"])
    yield "temperature", [
        ("t194_std", np.nanstd(t194, axis=1)),
        ("t194_dev", t194[:, 0] - np.nanmean(t194, axis=1)),
        ("t194_std30", np.nanstd(t194[:, :LI[30] + 1], axis=1)),
        ("t190_std", np.nanstd(np.expm1(col["s190"]), axis=1))]

    # seek / read / spin-up normalized values: how unstable, how far from usual
    yield "norm_stability", ([(f"{c}_std", np.nanstd(col[c], axis=1)) for c in NORMALIZED]
                             + [(f"{c}_dev", col[c][:, 0] - np.nanmean(col[c], axis=1))
                                for c in ("s7n", "s1n")])

    yield "startstop", [("startstop_rate90", (raw["s4"][:, 0] - raw["s4"][:, LI[90]]) / 90.0)]

    # log-slopes over 90 and 365 days, and how many lag intervals the counter rose in
    yield "slope", [(f"{c}_slope{s}", _slope(col[c], s)) for c in MAIN for s in SLOPE_SPANS]
    steps = []
    for c in MAIN:
        diff = np.diff(col[c], axis=1)               # older minus newer is positive
        steps.append((f"{c}_steps", (np.nan_to_num(diff) < -1e-6).sum(axis=1)))
    yield "steps", steps


def _layout():
    probe = np.zeros((2, len(LAGS), len(HIST_COLUMNS)), dtype=np.float16)
    return [(fam, [name for name, _ in cols]) for fam, cols in _families(probe)]


LAYOUT = _layout()
FAMILIES = {fam: names for fam, names in LAYOUT}
NAMES = [name for _, names in LAYOUT for name in names]


def _block(hist):
    return np.stack([np.asarray(c, dtype=np.float32) for _, cols in _families(hist)
                     for _, c in cols], axis=1)


def make_features(X, hist):
    """(n, 65) float32 + (n, 19, 20) float16 -> (n, 65 + len(NAMES)) float32."""
    assert hist.shape[1:] == (len(LAGS), len(HIST_COLUMNS)), hist.shape
    new = np.empty((X.shape[0], len(NAMES)), dtype=np.float32)
    for lo in range(0, X.shape[0], CHUNK):
        new[lo:lo + CHUNK] = _block(np.asarray(hist[lo:lo + CHUNK]))
    new[~np.isfinite(new)] = np.nan
    return np.hstack([np.asarray(X, dtype=np.float32), new])

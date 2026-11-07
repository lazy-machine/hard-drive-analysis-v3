"""Calibrate a block's raw output on the calibration rows, then score the held-out rows.

Every block goes through this same code: Platt per hazard bin with the true weights, then
weighted metrics with drive-level bootstrap intervals, paired against the reference run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from metrics import (
    DriveCells, RankedScores, bootstrap_drive_counts, weighted_brier,
    weighted_quantile_threshold,
)
from survival import (
    apply_platt, expand, failure_probability, fit_platt, hazards_to_survival, known_status,
)

HORIZONS = [30, 60, 90]
ROUNDS = 200
SEED = 20261107
FALSE_ALARM = 0.01
MIN_LEAD_DAYS = 7


def _platt(z, y, w) -> list[float]:
    coef = fit_platt(z, y, w)
    return coef if coef[1] > 0 else fit_platt(z, y, w, slope=1.0)


def calibrate(z, labels: pd.DataFrame, edges: list[int]) -> list[list[float]]:
    """One (a, b) per bin for hazard output (n, bins); one pair for binary output (n,)."""
    d, e, w = (labels[c].to_numpy() for c in ("duration_days", "event", "weight"))
    if z.ndim == 1:
        status = known_status(d, e, 30)
        keep = status >= 0
        return [_platt(z[keep], status[keep], w[keep])]
    idx, bins, y, w_rows = expand(d, e, w, edges)
    return [_platt(z[idx[bins == k], k], y[bins == k], w_rows[bins == k])
            for k in range(z.shape[1])]


def probabilities(z, coefs, edges: list[int]) -> dict[int, np.ndarray]:
    """{horizon: P(fail within horizon)}. Binary output only has the 30-day horizon."""
    if z.ndim == 1:
        return {30: apply_platt(z, coefs[0])}
    h = np.column_stack([apply_platt(z[:, k], c) for k, c in enumerate(coefs)])
    S = hazards_to_survival(h)
    return {H: failure_probability(S, edges, H) for H in HORIZONS}


def _drives(labels: pd.DataFrame):
    codes, uniques = pd.factorize(labels["serial_number"])
    failing = labels.groupby(codes)["event"].max().to_numpy()
    return codes, len(uniques), np.where(failing > 0, "failing", "healthy")


def _ci(v) -> list[float]:
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def score(p: dict[int, np.ndarray], p_cal: dict[int, np.ndarray], labels, cal_labels,
          reference: dict[int, np.ndarray] | None) -> dict:
    d, e, w = (labels[c].to_numpy() for c in ("duration_days", "event", "weight"))
    codes, n_drives, strata = _drives(labels)
    counts = list(bootstrap_drive_counts(n_drives, ROUNDS, SEED, strata))
    out = {}
    for H, ph in p.items():
        status = known_status(d, e, H)
        m = status >= 0
        y, ww, s, c = status[m], w[m], ph[m], codes[m]
        cells = DriveCells(RankedScores(s, y), c, {"w": ww})
        boot = np.array([cells.auc_ap(k, "w") for k in counts])
        ranked = RankedScores(s, y)
        row = {
            "ap": ranked.average_precision(ww), "ap_ci": _ci(boot[:, 1]),
            "auc": ranked.auc(ww), "auc_ci": _ci(boot[:, 0]),
            "base_rate": float((ww * y).sum() / ww.sum()),
            "positive_drives": int(np.unique(c[y == 1]).size),
            "observed_over_expected": float((ww * y).sum() / (ww * s).sum()),
        }
        base = row["base_rate"]
        ref_brier = weighted_brier(np.full(y.shape, base), y, ww)
        row["brier_skill"] = 1 - weighted_brier(s, y, ww) / ref_brier
        lead = (y == 0) | (d[m] >= MIN_LEAD_DAYS)
        row["ap_lead"] = RankedScores(s[lead], y[lead]).average_precision(ww[lead])
        # alert threshold from calibration rows, as evaluate.py does
        dc, ec, wc = (cal_labels[k].to_numpy() for k in ("duration_days", "event", "weight"))
        healthy = known_status(dc, ec, H) == 0
        thr = weighted_quantile_threshold(p_cal[H][healthy], wc[healthy], FALSE_ALARM)
        alert = s >= thr
        row["recall_at_1pct"] = float((ww * y * alert).sum() / (ww * y).sum())
        row["false_alarm_rate"] = float((ww * (1 - y) * alert).sum() / (ww * (1 - y)).sum())
        if reference is not None and H in reference:
            ref = DriveCells(RankedScores(reference[H][m], y), c, {"w": ww})
            rboot = np.array([ref.auc_ap(k, "w") for k in counts])
            gain = boot[:, 1] - rboot[:, 1]
            row["ap_gain"] = row["ap"] - RankedScores(reference[H][m], y).average_precision(ww)
            row["ap_gain_ci"] = _ci(gain)
        out[str(H)] = row
    return out


def score_run(run: Path, views: Path, edges: list[int], reference_run: Path | None) -> dict:
    held = views / "heldout"
    labels = pd.read_parquet(held / "score.labels.parquet")
    cal_labels = pd.read_parquet(held / "cal.labels.parquet")
    z_cal, z = np.load(run / "cal.logits.npy"), np.load(run / "score.logits.npy")
    coefs = calibrate(z_cal, cal_labels, edges)
    p = probabilities(z, coefs, edges)
    p_cal = probabilities(z_cal, coefs, edges)
    np.savez_compressed(run / "probabilities.npz", **{f"p{H}": v for H, v in p.items()})
    reference = None
    if reference_run is not None and (reference_run / "probabilities.npz").exists():
        ref = np.load(reference_run / "probabilities.npz")
        reference = {int(k[1:]): ref[k] for k in ref.files}
    result = score(p, p_cal, labels, cal_labels, reference)
    (run / "calibration.json").write_text(json.dumps(coefs))
    return result

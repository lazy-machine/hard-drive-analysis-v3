"""Evaluate every model on the test drives.

All metrics are weighted by inverse sampling probability, so they estimate real-world
values (true failure prevalence), and confidence intervals come from a drive-level
bootstrap. Only the alert threshold uses data outside test: it is set on validation drives.

Sections of metrics.json:
- discrimination: per horizon and model, ROC-AUC, PR-AUC (average precision) and Brier on
  snapshots whose status at the horizon is known, with bootstrap intervals, plus paired
  differences against the reference model (does SMART add information?).
- concordance: Harrell's C of each model's risk score against time to failure.
- alerting: a threshold with a fixed false-alarm budget on validation drives, then on test
  the false-alarm rate, precision, per-drive recall and detection by days before failure.
- life: how well the hazard models' remaining-life estimates match actual failure times.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from common import Progress, load_study, write_json
from metrics import (
    bootstrap_counts, concordance, km_failure, weighted_auc, weighted_average_precision,
    weighted_brier, weighted_quantile_threshold,
)
from survival import known_status

DURATION_BUCKETS = [0, 7, 14, 30, 60, 90, 180, 365]


def discover(columns) -> dict[str, dict]:
    """{model: {"kind": hazard|binary|rule, "horizons": [...]}} from prediction columns."""
    models: dict[str, dict] = {}
    for col in columns:
        if "__" not in col:
            continue
        name, qty = col.split("__", 1)
        m = models.setdefault(name, {"horizons": [], "kind": "binary"})
        if (hit := re.fullmatch(r"p(\d+)", qty)):
            m["horizons"].append(int(hit.group(1)))
        elif qty == "score":
            m["kind"] = "rule"
        elif qty == "median_days":
            m["kind"] = "hazard"
    return models


def score_of(df: pd.DataFrame, name: str, info: dict, horizon: int) -> np.ndarray | None:
    """The column that ranks snapshots for this horizon, or None if the model has none."""
    if info["kind"] == "rule":
        return df[f"{name}__score"].to_numpy()
    if horizon in info["horizons"]:
        return df[f"{name}__p{horizon}"].to_numpy()
    return None


def risk_of(df: pd.DataFrame, name: str, info: dict) -> np.ndarray:
    """A single risk score per snapshot for concordance (higher = fails sooner)."""
    if info["kind"] == "hazard":
        return -df[f"{name}__rmst_days"].to_numpy()
    if info["kind"] == "rule":
        return df[f"{name}__score"].to_numpy()
    return df[f"{name}__p{info['horizons'][0]}"].to_numpy()


def _interval(values: list[float]) -> list[float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v.size else [None, None]


def discrimination(test, models, horizons, reference, rounds, seed, log):
    drive_codes, drives = pd.factorize(test["serial_number"])
    rows, diffs, skipped = [], [], {}
    for H in horizons:
        status = known_status(test["duration_days"].to_numpy(), test["event"].to_numpy(), H)
        mask = status >= 0
        y, w = status[mask], test["weight"].to_numpy()[mask]
        if y.size == 0 or y.min() == y.max():
            # e.g. no test snapshot is followed for H days without failing
            skipped[H] = (f"{int(y.sum())} failed and {int((y == 0).sum())} known-healthy "
                          "test snapshots: ranking metrics need both")
            log(f"horizon {H}: skipped ({skipped[H]})")
            continue
        sub = test[mask]
        scores = {n: s[mask] for n, i in models.items()
                  if (s := score_of(test, n, i, H)) is not None}
        orders = {n: np.argsort(-s, kind="mergesort") for n, s in scores.items()}
        boot = {n: {"auc": [], "ap": []} for n in scores}
        boot_diff = {n: {"auc": [], "ap": []} for n in scores if n != reference}
        for mult in bootstrap_counts(drive_codes[mask], len(drives), rounds, seed + H):
            wb = w * mult
            point = {n: (weighted_auc(s, y, wb, orders[n]),
                         weighted_average_precision(s, y, wb, orders[n]))
                     for n, s in scores.items()}
            for n, (auc, ap) in point.items():
                boot[n]["auc"].append(auc)
                boot[n]["ap"].append(ap)
                if n in boot_diff and reference in point:
                    boot_diff[n]["auc"].append(point[reference][0] - auc)
                    boot_diff[n]["ap"].append(point[reference][1] - ap)
        pos_drives = sub.loc[y == 1, "serial_number"].nunique()
        for n, s in scores.items():
            row = {
                "horizon": H, "model": n, "kind": models[n]["kind"],
                "snapshots": int(mask.sum()), "positive_snapshots": int(y.sum()),
                "drives": int(sub["serial_number"].nunique()), "positive_drives": int(pos_drives),
                "base_rate": float(np.sum(w * y) / np.sum(w)),
                "auc": weighted_auc(s, y, w, orders[n]),
                "auc_ci": _interval(boot[n]["auc"]),
                "ap": weighted_average_precision(s, y, w, orders[n]),
                "ap_ci": _interval(boot[n]["ap"]),
                "brier": weighted_brier(s, y, w) if models[n]["kind"] != "rule" else None,
            }
            rows.append(row)
        if reference in scores:
            ref = _row(rows, H, reference)
            for n in boot_diff:
                other = _row(rows, H, n)
                diffs.append({
                    "horizon": H, "reference": reference, "other": n,
                    "auc_gain": ref["auc"] - other["auc"],
                    "auc_gain_ci": _interval(boot_diff[n]["auc"]),
                    "ap_gain": ref["ap"] - other["ap"],
                    "ap_gain_ci": _interval(boot_diff[n]["ap"]),
                    "share_of_rounds_reference_not_better":
                        float(np.mean(np.asarray(boot_diff[n]["auc"]) <= 0)),
                })
        log(f"discrimination at {H} days: {len(scores)} models")
    return rows, diffs, skipped


def _row(rows, H, name):
    return next(r for r in rows if r["horizon"] == H and r["model"] == name)


def calibration(test, models, horizons, groups=10) -> pd.DataFrame:
    """Mean predicted vs Kaplan-Meier observed failure probability per risk group."""
    out = []
    d, e, w = (test[c].to_numpy() for c in ("duration_days", "event", "weight"))
    for name, info in models.items():
        if info["kind"] == "rule":
            continue
        for H in info["horizons"]:
            if H not in horizons:
                continue
            p = test[f"{name}__p{H}"].to_numpy()
            order = np.argsort(p, kind="mergesort")
            cw = np.cumsum(w[order]) / w.sum()
            group = np.empty(p.size, dtype=int)
            group[order] = np.minimum((cw * groups).astype(int), groups - 1)
            for g in range(groups):
                m = group == g
                if not m.any():
                    continue
                out.append({
                    "model": name, "horizon": H, "group": g,
                    "snapshots": int(m.sum()), "drives": int(test["serial_number"][m].nunique()),
                    "predicted": float(np.sum(w[m] * p[m]) / np.sum(w[m])),
                    "observed_km": km_failure(d[m], e[m], w[m], H),
                })
    return pd.DataFrame(out)


def alerting(val, test, models, horizon, rate) -> tuple[list[dict], pd.DataFrame]:
    """Alert threshold from validation false-alarm budget, judged on test."""
    summary, curves = [], []
    st_val = known_status(val["duration_days"].to_numpy(), val["event"].to_numpy(), horizon)
    st_test = known_status(test["duration_days"].to_numpy(), test["event"].to_numpy(), horizon)
    w_val, w_test = val["weight"].to_numpy(), test["weight"].to_numpy()
    d_test = test["duration_days"].to_numpy()
    failing = test["event"].to_numpy() == 1
    for name, info in models.items():
        s_val, s_test = score_of(val, name, info, horizon), score_of(test, name, info, horizon)
        if s_val is None:
            continue
        healthy_val = st_val == 0
        threshold = weighted_quantile_threshold(s_val[healthy_val], w_val[healthy_val], rate)
        alert = s_test >= threshold
        healthy, positive = st_test == 0, st_test == 1
        tp = np.sum(w_test[alert & positive])
        fp = np.sum(w_test[alert & healthy])
        window = failing & (d_test < horizon)
        per_drive = pd.Series(alert[window]).groupby(test["serial_number"].to_numpy()[window]).any()
        summary.append({
            "model": name, "horizon": horizon, "threshold": float(threshold),
            "false_alarm_rate_val": float(np.sum(w_val[healthy_val] * (s_val[healthy_val] >= threshold))
                                          / np.sum(w_val[healthy_val])),
            "false_alarm_rate_test": float(np.sum(w_test[alert & healthy]) / np.sum(w_test[healthy])),
            "precision_test": float(tp / (tp + fp)) if tp + fp > 0 else None,
            "recall_snapshots_test": float(tp / np.sum(w_test[positive])),
            "failing_drives": int(per_drive.size),
            "failing_drives_alerted": int(per_drive.sum()),
        })
        for lo, hi in zip(DURATION_BUCKETS[:-1], DURATION_BUCKETS[1:]):
            m = failing & (d_test >= lo) & (d_test < hi)
            if m.any():
                curves.append({"model": name, "days_before_failure": f"{lo}-{hi - 1}",
                               "lo": lo, "snapshots": int(m.sum()),
                               "alerted": float(np.sum(w_test[m] * alert[m]) / np.sum(w_test[m]))})
    return summary, pd.DataFrame(curves)


def quantile_calibration(d, e, w, t) -> tuple[float | None, int]:
    """Weighted share of snapshots that failed before their predicted day t.

    Only snapshots with a finite t and a known outcome at t count: failed before t, or
    observed alive past t. For a calibrated q-quantile the share should be about q.
    """
    finite = np.isfinite(t)
    failed = finite & (e == 1) & (d < t)
    survived = finite & (d >= np.ceil(t))
    known = failed | survived
    if not known.any():
        return None, 0
    return float(np.sum(w[failed]) / np.sum(w[known])), int(known.sum())


def life(test, models, last_edge) -> tuple[list[dict], pd.DataFrame]:
    """Remaining-life estimates: are the predicted days right, and how early is a failure
    visible?"""
    summary, table = [], []
    d, e, w = (test[c].to_numpy() for c in ("duration_days", "event", "weight"))
    status = known_status(d, e, last_edge)
    for name, info in models.items():
        if info["kind"] != "hazard":
            continue
        med = test[f"{name}__median_days"].to_numpy()
        q10 = test[f"{name}__q10_days"].to_numpy()
        q90 = test[f"{name}__q90_days"].to_numpy()
        fails = status == 1
        covered = (d >= np.floor(q10)) & (d <= np.ceil(q90))
        finite = np.isfinite(med)

        def wmean(x, m):
            return float(np.sum(w[m] * x[m]) / np.sum(w[m])) if m.any() else None

        qcal = {}
        for q, col in ((0.1, q10), (0.5, med), (0.9, q90)):
            share, n = quantile_calibration(d, e, w, col)
            qcal[str(q)] = {"target": q, "share_failed_by_predicted_day": share, "snapshots": n}
        summary.append({
            "model": name,
            "quantile_calibration": qcal,
            "failing_snapshots": int(fails.sum()),
            "share_median_within_horizon": wmean(finite.astype(float), fails),
            "median_abs_error_days": wmean(np.abs(np.where(finite, med, 0) - d), fails & finite),
            "interval_q10_q90_coverage": wmean(covered.astype(float), fails),
            "healthy_snapshots": int((status == 0).sum()),
            "healthy_share_median_beyond_horizon": wmean((~finite).astype(float), status == 0),
            "mean_rmst_failing": wmean(test[f"{name}__rmst_days"].to_numpy(), fails),
            "mean_rmst_healthy": wmean(test[f"{name}__rmst_days"].to_numpy(), status == 0),
        })
        for lo, hi in zip(DURATION_BUCKETS[:-1], DURATION_BUCKETS[1:]):
            m = fails & (d >= lo) & (d < hi)
            if m.any():
                table.append({
                    "model": name, "actual_days_to_failure": f"{lo}-{hi - 1}", "lo": lo,
                    "snapshots": int(m.sum()),
                    "share_median_within_horizon": wmean(finite.astype(float), m),
                    "median_of_predicted_median": float(np.median(med[m])),
                    "coverage_q10_q90": wmean(covered.astype(float), m),
                })
    return summary, pd.DataFrame(table)


def evaluate(ctx):
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    ev, label = study["evaluation"], study["label"]
    preds = pd.read_parquet(ctx.inputs["predictions"])
    models = discover(preds.columns)
    reference = ctx.params["reference"]
    if reference not in models:
        raise ValueError(f"reference model '{reference}' has no predictions")
    val = preds[preds["split"] == "val"].reset_index(drop=True)
    test = preds[preds["split"] == "test"].reset_index(drop=True)
    log(f"{len(test)} test snapshots of {test['serial_number'].nunique()} drives")

    disc, diffs, skipped = discrimination(test, models, label["horizons"], reference,
                                 ev["bootstrap_rounds"], ev["bootstrap_seed"], log)

    cap = ctx.params.get("concordance_max_rows", 300_000)
    sample = test if len(test) <= cap else test.sample(cap, random_state=ev["bootstrap_seed"])
    conc = {n: concordance(risk_of(sample, n, i), sample["duration_days"].to_numpy(),
                           sample["event"].to_numpy(), sample["weight"].to_numpy())
            for n, i in models.items()}
    log("concordance done")

    calib = calibration(test, models, label["horizons"])
    alerts, detection = alerting(val, test, models, label["binary_horizon"],
                                 ev["alert_false_alarm_rate"])
    life_summary, life_table = life(test, models, label["bin_edges"][-1])

    calib.to_csv(ctx.outputs["calibration"], index=False)
    detection.to_csv(ctx.outputs["detection"], index=False)
    life_table.to_csv(ctx.outputs["life"], index=False)
    write_json(ctx.outputs["metrics"], {
        "reference": reference,
        "models": models,
        "test": {"snapshots": len(test), "drives": int(test["serial_number"].nunique()),
                 "failing_drives": int(test.loc[test["event"] == 1, "serial_number"].nunique())},
        "bootstrap_rounds": ev["bootstrap_rounds"],
        "discrimination": disc,
        "skipped_horizons": skipped,
        "reference_gain": diffs,
        "concordance": conc,
        "concordance_rows": len(sample),
        "alerting": alerts,
        "life": life_summary,
    })
    H = label["binary_horizon"]
    return {f"auc{H}_{reference}": _row(disc, H, reference)["auc"],
            f"c_{reference}": conc[reference]}

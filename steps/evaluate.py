"""Evaluate every model on the test drives.

All metrics are weighted by inverse sampling probability, so they estimate real-world
values (true failure prevalence), and confidence intervals come from a drive-level
bootstrap that resamples failing and healthy drives separately (as they were sampled).
Only the alert threshold uses data outside test: it is set on the validation drives that
calibrate the models.

Units: discrimination, calibration and precision are per drive-day snapshot; the
"failing drives alerted" counts and the auc_drive column are per drive.

Sections of metrics.json:
- discrimination: per horizon and model, ROC-AUC, PR-AUC (average precision) and Brier
  (with skill against the base rate) on snapshots whose status at the horizon is known;
  the same ROC-AUC and PR-AUC with inverse-probability-of-censoring weights (IPCW) instead
  of dropping unknown rows; and a drive-level ROC-AUC on one random snapshot per drive.
  All with bootstrap intervals, plus paired differences against the reference model.
- slices: the same metrics on parts of the test set: positives at least min_lead_days
  before failure, silent failures (no critical counter ever above zero) and the others,
  per vendor, per capacity class, and drives already in service when the panel starts.
- concordance: Harrell's and Uno's C of each model's risk score against time to failure,
  on whole drives up to a row cap, with bootstrap intervals.
- alerting: thresholds for several false-alarm budgets on validation drives, then on test
  the false-alarm rate, precision, per-drive recall, early detection and intervals.
- calibration_in_the_large and drift: predicted vs observed risk per split and year, the
  ratio with an interval, and whether test years fall outside the validation-year band.
- retirement: do drives that leave the panel without failing look riskier beforehand?
- life: how well the hazard models' remaining-life estimates match actual failure times.
"""

from __future__ import annotations

import multiprocessing
import os
import re
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from common import Progress, left_truncated, load_study, val_roles, write_json
from metrics import (
    DriveCells, RankedScores, bootstrap_drive_counts, censoring_survival, concordance, ipcw_weights,
    km_failure, one_per_drive, uno_concordance, weighted_auc, weighted_average_precision,
    weighted_brier, weighted_quantile_threshold,
)
from survival import known_status

COHORT_COLUMNS = ["serial_number", "stratum", "drive_weight", "vendor", "capacity_bytes",
                  "first_date", "last_date", "failure_date"]


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


def _workers() -> int:
    return int(os.environ.get("HDA_THREADS", 0)) or os.cpu_count() or 4


_TASK = None


def _run_task(i):
    return _TASK(i)


def parallel_rounds(fn, n: int) -> list:
    """[fn(0), ..., fn(n - 1)] in order, on forked worker processes.

    Bootstrap rounds are independent and their random draws are made before this call,
    so the results are the same as a serial loop. Forked workers share the parent's
    arrays copy-on-write; threads would not help, because the heavy numpy calls here
    (bincount, fancy indexing) hold the GIL.
    """
    global _TASK
    workers = min(_workers(), n)
    if workers <= 1:
        return [fn(i) for i in range(n)]
    _TASK = fn
    try:
        with warnings.catch_warnings():
            # Arrow's idle reader threads hold no lock the workers use
            warnings.filterwarnings("ignore", message=".*fork.*", category=DeprecationWarning)
            with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("fork")
                                     ) as pool:
                return list(pool.map(_run_task, range(n), chunksize=max(1, n // (4 * workers))))
    finally:
        _TASK = None


def _interval(values: list[float]) -> list[float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v.size else [None, None]


class Drives:
    """Test-set drive bookkeeping shared by every section: drive codes per row, the
    stratum of each drive for the bootstrap, and the censoring distribution for IPCW."""

    def __init__(self, test: pd.DataFrame):
        self.codes, uniques = pd.factorize(test["serial_number"])
        self.n = len(uniques)
        first = pd.Series(np.arange(len(test))).groupby(self.codes).first().to_numpy()
        self.strata = test["stratum"].to_numpy()[first]
        self.d, self.e, self.w = (test[c].to_numpy() for c in ("duration_days", "event", "weight"))
        self.drive_w = test["drive_weight"].to_numpy()
        self.G = censoring_survival(self.d, self.e, self.w)

    def boot(self, rounds, seed):
        return bootstrap_drive_counts(self.n, rounds, seed, self.strata)




def _ranking_metrics(test, D: Drives, models, H, mask, rounds, seed, reference=None,
                     drive_level=False):
    """ROC-AUC/PR-AUC (+ IPCW, + drive-level) with bootstrap intervals on rows `mask` at
    horizon H. Returns ({model: row}, {model: bootstrap AUC/AP gains of the reference})."""
    status = known_status(D.d, D.e, H)
    mask = mask & (status >= 0)
    y, w = status[mask], D.w[mask]
    if y.size == 0 or y.min() == y.max():
        return None, None
    iw = ipcw_weights(D.d, D.e, D.w, H, D.G)[mask]
    codes, dw = D.codes[mask], D.drive_w[mask]
    scores = {n: s[mask] for n, i in models.items() if (s := score_of(test, n, i, H)) is not None}
    ranked = {n: RankedScores(s, y) for n, s in scores.items()}
    orders = {n: r.order for n, r in ranked.items()}
    keys = ["auc", "ap", "auc_ipcw", "ap_ipcw"] + (["auc_drive"] if drive_level else [])
    boot = {n: {k: [] for k in keys} for n in scores}
    gains = {n: {"auc": [], "ap": []} for n in scores if n != reference}
    rng = np.random.default_rng(seed)
    all_counts = list(D.boot(rounds, seed))
    # drawn up front, in round order, so the worker processes do not change the random
    # stream
    grouped = np.argsort(codes, kind="stable")
    picks = [one_per_drive(codes, rng, grouped) for _ in all_counts] if drive_level else None

    cells = {n: DriveCells(r, codes, {"w": w, "ipcw": iw}) for n, r in ranked.items()}

    def one_round(i):
        counts = all_counts[i]
        res = {}
        for n, c in cells.items():
            auc, ap = c.auc_ap(counts, "w")
            auc_ipcw, ap_ipcw = c.auc_ap(counts, "ipcw")
            res[n] = {"auc": auc, "ap": ap, "auc_ipcw": auc_ipcw, "ap_ipcw": ap_ipcw}
        if drive_level:
            mult = counts[codes]
            pick = picks[i][mult[picks[i]] > 0]
            for n, s in scores.items():
                res[n]["auc_drive"] = weighted_auc(s[pick], y[pick], (dw * mult)[pick])
        return res

    for res in parallel_rounds(one_round, len(all_counts)):
        for n in scores:
            for k in keys:
                boot[n][k].append(res[n][k])
        for n in gains:
            if reference in res:
                gains[n]["auc"].append(res[reference]["auc"] - res[n]["auc"])
                gains[n]["ap"].append(res[reference]["ap"] - res[n]["ap"])
    base = float(np.sum(w * y) / np.sum(w))
    if drive_level:
        prng = np.random.default_rng(seed + 1)
        point_picks = [one_per_drive(codes, prng, grouped) for _ in range(20)]
    out = {}
    for n, s in scores.items():
        o = orders[n]
        row = {
            "snapshots": int(mask.sum()), "positive_snapshots": int(y.sum()),
            "drives": int(np.unique(codes).size),
            "positive_drives": int(np.unique(codes[y == 1]).size),
            "base_rate": base,
            "auc": weighted_auc(s, y, w, o), "auc_ci": _interval(boot[n]["auc"]),
            "ap": weighted_average_precision(s, y, w, o), "ap_ci": _interval(boot[n]["ap"]),
            "auc_ipcw": weighted_auc(s, y, iw, o), "auc_ipcw_ci": _interval(boot[n]["auc_ipcw"]),
            "ap_ipcw": weighted_average_precision(s, y, iw, o),
            "ap_ipcw_ci": _interval(boot[n]["ap_ipcw"]),
        }
        if drive_level:
            # the point estimate averages 20 draws of one snapshot per drive (the same
            # 20 draws for every model)
            draws = [weighted_auc(s[p], y[p], dw[p]) for p in point_picks]
            row["auc_drive"] = float(np.nanmean(draws)) if np.isfinite(draws).any() else None
            row["auc_drive_ci"] = _interval(boot[n]["auc_drive"])
        out[n] = row
    return out, gains


def discrimination(test, D, models, horizons, reference, rounds, seed, log):
    rows, diffs, skipped = [], [], {}
    everything = np.ones(len(test), dtype=bool)
    for H in horizons:
        res, gains = _ranking_metrics(test, D, models, H, everything, rounds, seed + H,
                                      reference, drive_level=True)
        if res is None:
            # e.g. no test snapshot is followed for H days without failing
            st = known_status(D.d, D.e, H)
            skipped[H] = (f"{int((st == 1).sum())} failed and {int((st == 0).sum())} "
                          "known-healthy test snapshots: ranking metrics need both")
            log(f"horizon {H}: skipped ({skipped[H]})")
            continue
        for n, r in res.items():
            brier = None
            skill = None
            if models[n]["kind"] != "rule":
                st = known_status(D.d, D.e, H)
                m = st >= 0
                brier = weighted_brier(test[f"{n}__p{H}"].to_numpy()[m], st[m], D.w[m])
                ref = r["base_rate"] * (1 - r["base_rate"])   # Brier of always saying the base rate
                skill = 1 - brier / ref if ref > 0 else None
            rows.append({"horizon": H, "model": n, "kind": models[n]["kind"], **r,
                         "brier": brier, "brier_skill": skill})
        if reference in res:
            for n, g in gains.items():
                diffs.append({
                    "horizon": H, "reference": reference, "other": n,
                    "auc_gain": res[reference]["auc"] - res[n]["auc"],
                    "auc_gain_ci": _interval(g["auc"]),
                    "ap_gain": res[reference]["ap"] - res[n]["ap"],
                    "ap_gain_ci": _interval(g["ap"]),
                    "share_of_rounds_reference_not_better":
                        float(np.mean(np.asarray(g["auc"]) <= 0)),
                })
        log(f"discrimination at {H} days: {len(res)} models")
    return rows, diffs, skipped


def _row(rows, H, name):
    return next(r for r in rows if r["horizon"] == H and r["model"] == name)


def silent_drives(test, D) -> np.ndarray:
    """Per test drive: fails in the test period with no critical counter ever above zero
    in its test snapshots (the failures SMART gives no classic warning for)."""
    warned = np.zeros(D.n, dtype=bool)
    np.logical_or.at(warned, D.codes, test["critical_nonzero"].to_numpy())
    fails = np.zeros(D.n, dtype=bool)
    np.logical_or.at(fails, D.codes, D.e == 1)
    return fails & ~warned


def slices(test, D, models, horizons, binary_horizon, rounds, seed, cfg, log):
    """The ranking metrics on parts of the test set. Positive-side slices keep every
    negative and restrict the positives; population slices restrict both."""
    silent = silent_drives(test, D)[D.codes]
    positive_side = {
        f"positives >= {cfg['min_lead_days']} days before failure": D.d >= cfg["min_lead_days"],
        "silent failures (no critical counter above zero)": silent,
        "failures with a critical counter above zero": ~silent,
    }
    cap = test["capacity_bytes"].to_numpy() / 1e12
    population = {f"vendor {v}": (test["vendor"] == v).to_numpy()
                  for v in sorted(test["vendor"].dropna().unique())}
    population.update({
        f"capacity >= {cfg['capacity_split_tb']} TB": cap >= cfg["capacity_split_tb"],
        f"capacity < {cfg['capacity_split_tb']} TB": cap < cfg["capacity_split_tb"],
        "in service before the panel starts": test["left_truncated"].to_numpy() == 1,
        "first seen after the panel starts": test["left_truncated"].to_numpy() == 0,
    })
    out = []
    for H in horizons:
        status = known_status(D.d, D.e, H)
        todo = dict(positive_side)
        if H == binary_horizon:
            todo.update(population)
        for name, keep in todo.items():
            mask = (status == 0) | keep if name in positive_side else keep
            res, _ = _ranking_metrics(test, D, models, H, mask, rounds, seed + H)
            if res is None:
                continue
            out += [{"slice": name, "horizon": H, "model": n, **r} for n, r in res.items()]
        log(f"slices at {H} days")
    return out


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


def calibration_in_the_large(preds, models, horizons, binary_horizon, rounds, seed) -> list[dict]:
    """Mean predicted vs Kaplan-Meier observed risk per split and calendar year.

    Validation drives share the training era; test is 2024+. If validation is calibrated
    but test years are not, failure rates moved over time (drift), not the model. At the
    binary horizon the predicted/observed ratio gets a drive-bootstrap interval (the
    observed risk is shared by all models, so one KM per round serves them all).
    """
    rows = []
    year = pd.to_datetime(preds["date"]).dt.year
    prob = {n: i for n, i in models.items() if i["kind"] != "rule"}
    for (split, yr), g in preds.groupby([preds["split"], year]):
        d, e, w = (g[c].to_numpy() for c in ("duration_days", "event", "weight"))
        codes, uniques = pd.factorize(g["serial_number"])
        boot = {}
        if binary_horizon in horizons:
            cols = {n: g[f"{n}__p{binary_horizon}"].to_numpy() for n, i in prob.items()
                    if binary_horizon in i["horizons"]}
            boot = {n: [] for n in cols}
            for counts in bootstrap_drive_counts(len(uniques), rounds, seed + int(yr)):
                wb = w * counts[codes]
                obs = km_failure(d, e, wb, binary_horizon)
                for n, pcol in cols.items():
                    boot[n].append(np.sum(wb * pcol) / np.sum(wb) / obs if obs > 0 else np.nan)
        for name, info in prob.items():
            for H in info["horizons"]:
                if H not in horizons:
                    continue
                pred = float(np.average(g[f"{name}__p{H}"], weights=w))
                obs = km_failure(d, e, w, H)
                row = {"split": split, "year": int(yr), "model": name, "horizon": H,
                       "snapshots": len(g), "predicted": pred, "observed_km": obs,
                       "ratio": pred / obs if obs > 0 else None}
                if H == binary_horizon and name in boot:
                    row["ratio_ci"] = _interval(boot[name])
                rows.append(row)
    return rows


def drift(cal_rows, horizon, log) -> list[dict]:
    """Per model: the band of validation-year ratios (predicted / observed), whether the
    last pre-test year already leaves the band of the earlier years (an early warning
    that needs no test data), and which test years fall outside the band."""
    out = []
    df = pd.DataFrame([r for r in cal_rows if r["horizon"] == horizon and r["ratio"] is not None])
    for name, g in df.groupby("model", sort=False):
        val = g[g["split"] == "val"].sort_values("year")
        if len(val) < 3:
            continue
        lo, hi = float(val["ratio"].min()), float(val["ratio"].max())
        earlier, last = val.iloc[:-1], val.iloc[-1]
        e_lo, e_hi = float(earlier["ratio"].min()), float(earlier["ratio"].max())
        test_years = [{"year": int(r["year"]), "ratio": float(r["ratio"]),
                       "ratio_ci": r.get("ratio_ci"), "outside_band": not lo <= r["ratio"] <= hi}
                      for _, r in g[g["split"] == "test"].sort_values("year").iterrows()]
        row = {"model": name, "horizon": horizon, "val_band": [lo, hi],
               "last_val_year": int(last["year"]), "last_val_ratio": float(last["ratio"]),
               "last_val_year_outside_earlier_band": not e_lo <= last["ratio"] <= e_hi,
               "test_years": test_years}
        out.append(row)
        flagged = [t["year"] for t in test_years if t["outside_band"]]
        if flagged or row["last_val_year_outside_earlier_band"]:
            log(f"DRIFT {name}: test years outside the validation band {lo:.2f}-{hi:.2f}: "
                f"{flagged}; last validation year outside the earlier band: "
                f"{row['last_val_year_outside_earlier_band']}")
    return out


def retirement(preds, models, horizon, thresholds) -> list[dict]:
    """Drives that leave the panel without failing: were they riskier beforehand?

    For each split and year Y, drives that never fail and have snapshots in Y are split
    into those that stop reporting before the end of Y+1 (or the panel end) and those
    still reporting then. If retirement were unrelated to health (the censoring
    assumption), both groups would carry about the same predicted risk in year Y.
    """
    out = []
    panel_end = pd.to_datetime(preds["last_date"]).max()
    date = pd.to_datetime(preds["date"])
    never = preds["failure_date"].isna().to_numpy()
    last = pd.to_datetime(preds["last_date"])
    groups = preds[never].groupby([preds["split"][never], date[never].dt.year]).groups
    for (split, yr), idx in groups.items():
        horizon_end = min(pd.Timestamp(year=int(yr) + 1, month=12, day=31), panel_end)
        if pd.Timestamp(year=int(yr) + 1, month=1, day=1) > panel_end:
            continue                                    # no following year to leave in
        g = preds.loc[idx]
        left = (last.loc[idx] < horizon_end).to_numpy()
        w = g["weight"].to_numpy()
        for name, info in models.items():
            if info["kind"] == "rule" or horizon not in info["horizons"]:
                continue
            pcol = g[f"{name}__p{horizon}"].to_numpy()
            t = thresholds.get(name)
            row = {"split": split, "year": int(yr), "model": name,
                   "drives_left": int(g["serial_number"][left].nunique()),
                   "drives_stayed": int(g["serial_number"][~left].nunique())}
            for key, m in (("left", left), ("stayed", ~left)):
                row[f"mean_p_{key}"] = float(np.average(pcol[m], weights=w[m])) if m.any() else None
                row[f"share_above_threshold_{key}"] = (
                    float(np.sum(w[m] * (pcol[m] >= t)) / np.sum(w[m]))
                    if m.any() and t is not None else None)
            row["risk_ratio"] = (row["mean_p_left"] / row["mean_p_stayed"]
                                 if row["mean_p_left"] and row["mean_p_stayed"] else None)
            out.append(row)
    return out


def alerting(val, test, D, models, horizon, rates, main_rate, lead, edges, rounds, seed):
    """Alert thresholds from validation false-alarm budgets, judged on test.

    Precision counts only alerts whose outcome at the horizon is known; the share of
    alerts whose outcome is unknown (censored by the panel end) is reported next to it,
    with the precision that counts them as false alarms.
    """
    summary, curves = [], []
    st_val = known_status(val["duration_days"].to_numpy(), val["event"].to_numpy(), horizon)
    st = known_status(D.d, D.e, horizon)
    w_val = val["weight"].to_numpy()
    healthy_val = st_val == 0
    healthy, positive, unknown = st == 0, st == 1, st == -1
    window = (D.e == 1) & (D.d < horizon)                     # failing drives' last days
    failing_drives = np.unique(D.codes[window])
    counts_list = list(D.boot(rounds, seed))
    for name, info in models.items():
        s_val, s_test = score_of(val, name, info, horizon), score_of(test, name, info, horizon)
        if s_val is None:
            continue
        for rate in rates:
            threshold = weighted_quantile_threshold(s_val[healthy_val], w_val[healthy_val], rate)
            alert = s_test >= threshold
            any_alert = np.zeros(D.n, dtype=bool)
            np.logical_or.at(any_alert, D.codes[window], alert[window])
            early = window & (D.d >= lead)
            early_alert = np.zeros(D.n, dtype=bool)
            np.logical_or.at(early_alert, D.codes[early], alert[early])

            def stats(w, drive_counts, alert=alert, any_alert=any_alert,
                      early_alert=early_alert):
                tp, fp = np.sum(w[alert & positive]), np.sum(w[alert & healthy])
                unk = np.sum(w[alert & unknown])
                f = drive_counts[failing_drives]
                return {
                    "false_alarm_rate_test": float(fp / np.sum(w[healthy])),
                    "precision_test": float(tp / (tp + fp)) if tp + fp > 0 else None,
                    "precision_unknown_as_false": float(tp / (tp + fp + unk))
                    if tp + fp + unk > 0 else None,
                    "unknown_alert_share": float(unk / (tp + fp + unk))
                    if tp + fp + unk > 0 else None,
                    "recall_snapshots_test": float(tp / np.sum(w[positive])),
                    "share_failing_drives_alerted":
                        float(np.sum(f * any_alert[failing_drives]) / f.sum()),
                    "share_failing_drives_alerted_early":
                        float(np.sum(f * early_alert[failing_drives]) / f.sum()),
                }

            point = stats(D.w, np.ones(D.n))
            boot = [stats(D.w * c[D.codes], c) for c in counts_list]
            row = {"model": name, "horizon": horizon, "budget": rate, "threshold": float(threshold),
                   "false_alarm_rate_val":
                       float(np.sum(w_val[healthy_val] * (s_val[healthy_val] >= threshold))
                             / np.sum(w_val[healthy_val])),
                   "failing_drives": int(failing_drives.size),
                   "failing_drives_alerted": int(any_alert[failing_drives].sum()),
                   "failing_drives_alerted_early": int(early_alert[failing_drives].sum()),
                   "early_days": lead, **point}
            for k in point:
                row[f"{k}_ci"] = _interval([b[k] for b in boot if b[k] is not None])
            summary.append(row)
            if rate != main_rate:
                continue
            for lo, hi in zip(edges[:-1], edges[1:], strict=True):
                m = (D.e == 1) & (D.d >= lo) & (D.d < hi)
                if m.any():
                    curves.append({"model": name, "days_before_failure": f"{lo}-{hi - 1}",
                                   "lo": lo, "snapshots": int(m.sum()),
                                   "alerted": float(np.sum(D.w[m] * alert[m]) / np.sum(D.w[m]))})
    return summary, pd.DataFrame(curves)


def concordance_table(test, models, cap, rounds, seed, tau, binary_horizon, log):
    """Harrell's and Uno's C on whole drives (up to `cap` rows), with drive bootstrap
    intervals. Every probability model is also scored by its p<binary_horizon>, so the
    models can be compared on the same kind of score."""
    rng = np.random.default_rng(seed)
    codes, uniques = pd.factorize(test["serial_number"])
    sizes = np.bincount(codes)
    order = rng.permutation(len(uniques))
    keep_drive = np.zeros(len(uniques), dtype=bool)
    keep_drive[order[np.cumsum(sizes[order]) <= cap]] = True
    sample = test[keep_drive[codes]].reset_index(drop=True)
    D = Drives(sample)
    out = []
    for name, info in models.items():
        scores = {"-rmst_days" if info["kind"] == "hazard" else
                  "score" if info["kind"] == "rule" else f"p{info['horizons'][0]}":
                  risk_of(sample, name, info)}
        if info["kind"] == "hazard":
            scores[f"p{binary_horizon}"] = sample[f"{name}__p{binary_horizon}"].to_numpy()
        for i, (label, r) in enumerate(scores.items()):
            row = {"model": name, "score": label,
                   "harrell": concordance(r, D.d, D.e, D.w),
                   "uno": uno_concordance(r, D.d, D.e, D.w, tau, D.G)}
            if i == 0:   # intervals for each model's main score only (Fenwick tree per round)
                all_counts = list(D.boot(rounds, seed))

                def one_round(i, r=r, all_counts=all_counts):
                    wb = D.w * all_counts[i][D.codes]
                    return (concordance(r, D.d, D.e, wb),
                            uno_concordance(r, D.d, D.e, wb, tau, D.G))

                h, u = zip(*parallel_rounds(one_round, len(all_counts)), strict=True)
                row["harrell_ci"], row["uno_ci"] = _interval(h), _interval(u)
            out.append(row)
    log(f"concordance on {len(sample)} rows of {D.n} drives")
    return out, len(sample), D.n


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


def life(test, models, edges) -> tuple[list[dict], pd.DataFrame]:
    """Remaining-life estimates: are the predicted days right, and how early is a failure
    visible?"""
    summary, table = [], []
    d, e, w = (test[c].to_numpy() for c in ("duration_days", "event", "weight"))
    status = known_status(d, e, edges[-1])
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
            # only failing snapshots with a finite predicted median (the rest are "> 1 year")
            "median_abs_error_days": wmean(np.abs(med - d), fails & finite),
            "median_abs_error_snapshots": int((fails & finite).sum()),
            "share_finite_median_all": wmean(finite.astype(float), np.ones(d.size, dtype=bool)),
            "interval_q10_q90_coverage": wmean(covered.astype(float), fails),
            "healthy_snapshots": int((status == 0).sum()),
            "healthy_share_median_beyond_horizon": wmean((~finite).astype(float), status == 0),
            "mean_rmst_failing": wmean(test[f"{name}__rmst_days"].to_numpy(), fails),
            "mean_rmst_healthy": wmean(test[f"{name}__rmst_days"].to_numpy(), status == 0),
        })
        for lo, hi in zip(edges[:-1], edges[1:], strict=True):
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
    edges, H = label["bin_edges"], label["binary_horizon"]
    preds = pd.read_parquet(ctx.inputs["predictions"])
    cohort = pd.read_parquet(ctx.inputs["cohort"], columns=COHORT_COLUMNS)
    cohort["left_truncated"] = left_truncated(cohort["first_date"])
    preds = preds.merge(cohort, on="serial_number", how="left", validate="many_to_one")
    models = discover(preds.columns)
    reference = ctx.params["reference"]
    if reference not in models:
        raise ValueError(f"reference model '{reference}' has no predictions")
    val = preds[preds["split"] == "val"].reset_index(drop=True)
    val_cal = val[val_roles(val["serial_number"], study["split"]["calibration_share"])]
    val_cal = val_cal.reset_index(drop=True)
    test = preds[preds["split"] == "test"].reset_index(drop=True)
    D = Drives(test)
    rounds, seed = ev["bootstrap_rounds"], ev["bootstrap_seed"]
    log(f"{len(test)} test snapshots of {D.n} drives; {len(val_cal)} validation snapshots "
        "for alert thresholds")

    disc, diffs, skipped = discrimination(test, D, models, label["horizons"], reference,
                                          rounds, seed, log)
    slice_rows = slices(test, D, models, label["horizons"], H, rounds, seed, ev, log)

    conc, conc_rows, conc_drives = concordance_table(
        test, models, ctx.params.get("concordance_max_rows", 300_000),
        ev.get("concordance_bootstrap_rounds", rounds), seed, edges[-1], H, log)

    calib = calibration(test, models, label["horizons"])
    rates = sorted(set(ev.get("alert_false_alarm_rates", [])) | {ev["alert_false_alarm_rate"]})
    alerts, detection = alerting(val_cal, test, D, models, H, rates, ev["alert_false_alarm_rate"],
                                 ev["min_lead_days"], edges, rounds, seed)
    log("alerting done")
    life_summary, life_table = life(test, models, edges)
    cal_rows = calibration_in_the_large(preds, models, label["horizons"], H, rounds, seed)
    thresholds = {a["model"]: a["threshold"] for a in alerts
                  if a["budget"] == ev["alert_false_alarm_rate"]}
    retire = retirement(preds, models, H, thresholds)
    log("calibration over time and retirement done")

    calib.to_csv(ctx.outputs["calibration"], index=False)
    detection.to_csv(ctx.outputs["detection"], index=False)
    life_table.to_csv(ctx.outputs["life"], index=False)
    silent = silent_drives(test, D)
    write_json(ctx.outputs["metrics"], {
        "reference": reference,
        "models": models,
        "test": {"snapshots": len(test), "drives": D.n,
                 "failing_drives": int(test.loc[test["event"] == 1, "serial_number"].nunique()),
                 "silent_failing_drives": int(silent.sum())},
        "binary_horizon": H,
        "bootstrap_rounds": rounds,
        "bootstrap": "drive-level, failing and healthy strata resampled separately",
        "discrimination": disc,
        "skipped_horizons": skipped,
        "reference_gain": diffs,
        "slices": slice_rows,
        "concordance": conc,
        "concordance_rows": conc_rows,
        "concordance_drives": conc_drives,
        "concordance_tau_days": edges[-1],
        "alerting": alerts,
        "alert_false_alarm_rate": ev["alert_false_alarm_rate"],
        "calibration_in_the_large": cal_rows,
        "drift": drift(cal_rows, H, log),
        "retirement": retire,
        "life": life_summary,
    })
    main = next(c for c in conc if c["model"] == reference)
    return {f"auc{H}_{reference}": _row(disc, H, reference)["auc"],
            f"c_{reference}": main["harrell"]}

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
- full_follow_up: the ranking metrics on snapshots dated at least H - 1 days before the
  panel ends, so positives and negatives face the same administrative cutoff (retired
  drives are still censored), with paired differences against the reference model.
- calibration_by_group: the binary-horizon predicted/observed ratio of the reference
  model per split, year and group (capacity class, vendor, the firmware_model and the
  rest of its vendor), and the weighted fleet composition per split and year.
- weekly_alerts: alerts per drive with every drive on the same weekly schedule (its
  stride days), so failing and non-failing drives are watched alike: per budget, the
  share of failing drives alerted in their last H days and of non-failing drives alerted
  at least once; and, at fixed shares of non-failing drives alerted, the share of failing
  drives each model catches, with paired bootstrap differences.
- seed_spread: ranking metrics of the seed replicates (models named <family>_seed<N>),
  which every other section leaves out, and the survival-minus-classifier difference per
  seed pair.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import re
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from common import (
    Progress, left_truncated, load_sample, load_study, stable_unit, val_roles, write_json,
)
from metrics import (
    DriveCells, RankedScores, bootstrap_drive_counts, censoring_survival, concordance,
    ipcw_weights, km_failure, one_per_drive, uno_concordance, weighted_auc,
    weighted_average_precision, weighted_brier, weighted_quantile_threshold,
)
from survival import known_status

COHORT_COLUMNS = ["serial_number", "stratum", "drive_weight", "model", "vendor",
                  "capacity_bytes", "first_date", "last_date", "failure_date"]
SEED = re.compile(r"^(?P<family>.+)_seed(?P<k>\d+)$")


def split_seeds(models: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """(models, seed replicates): names ending in _seed<N> go to the second dict."""
    main = {n: i for n, i in models.items() if not SEED.match(n)}
    return main, {n: i for n, i in models.items() if SEED.match(n)}


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
    """Worker processes for bootstrap rounds. HDA_THREADS, which also sets the DuckDB and
    LightGBM threads, caps them; unset (or 0) means one per CPU."""
    return int(os.environ.get("HDA_THREADS", 0)) or os.cpu_count() or 4


# The function parallel_rounds runs. A closure cannot be pickled, so it reaches the
# workers as this module global, which a forked child inherits. Not re-entrant: one
# parallel_rounds call at a time.
_TASK = None


def _run_task(i):
    return _TASK(i)


def parallel_rounds(fn, n: int) -> list:
    """[fn(0), ..., fn(n - 1)] in order, on forked worker processes.

    Bootstrap rounds are independent and their random draws are made before this call,
    so the results are the same as a serial loop. Forked workers share the parent's
    arrays copy-on-write; threads would not help, because the heavy numpy calls here
    (bincount, fancy indexing) hold the GIL.

    Precondition for fork safety: `fn` only runs numpy on arrays already in memory. The
    parent has idle Arrow/DuckDB threads from reading parquet; a child that called into
    those libraries could hit a lock one of them held at fork time.
    """
    global _TASK
    workers = min(_workers(), n)
    if workers <= 1:
        return [fn(i) for i in range(n)]
    _TASK = fn
    pool = None
    try:
        with warnings.catch_warnings():
            # Python warns about fork with threads alive; see the precondition above
            warnings.filterwarnings("ignore", message=".*fork.*", category=DeprecationWarning)
            pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("fork"))
            return list(pool.map(_run_task, range(n), chunksize=max(1, n // (4 * workers))))
    finally:
        if pool is not None:
            pool.shutdown(cancel_futures=True)   # a failed round stops the rest
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
        self.weight_of_drive = self.drive_w[first]
        self.fails = np.zeros(self.n, dtype=bool)
        np.logical_or.at(self.fails, self.codes, self.e == 1)
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
    keys = ["auc", "ap", "auc_ipcw", "ap_ipcw"] + (["auc_drive"] if drive_level else [])
    boot = {n: {k: [] for k in keys} for n in scores}
    gains = {n: {"auc": [], "ap": []} for n in scores if n != reference}
    rng = np.random.default_rng(seed)
    all_counts = list(D.boot(rounds, seed))
    if drive_level:
        # drawn up front, in round order, so the worker processes do not change the
        # random stream
        grouped = np.argsort(codes, kind="stable")
        picks = [one_per_drive(codes, rng, grouped) for _ in all_counts]

    cells = {n: DriveCells(r, codes, {"w": w, "ipcw": iw}) for n, r in ranked.items()}

    def one_round(i):
        counts = all_counts[i]
        res = {}
        for n, c in cells.items():
            auc, ap = c.auc_ap(counts, "w")
            auc_ipcw, ap_ipcw = c.auc_ap(counts, "ipcw")
            res[n] = {"auc": auc, "ap": ap, "auc_ipcw": auc_ipcw, "ap_ipcw": ap_ipcw}
        if drive_level:
            # one snapshot per drive, weighted by how often its drive was drawn
            mult = counts[codes[picks[i]]]
            pick, mult = picks[i][mult > 0], mult[mult > 0]
            for n, s in scores.items():
                res[n]["auc_drive"] = weighted_auc(s[pick], y[pick], dw[pick] * mult)
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
        r = ranked[n]
        row = {
            "snapshots": int(mask.sum()), "positive_snapshots": int(y.sum()),
            "drives": int(np.unique(codes).size),
            "positive_drives": int(np.unique(codes[y == 1]).size),
            "base_rate": base,
            "auc": r.auc(w), "auc_ci": _interval(boot[n]["auc"]),
            "ap": r.average_precision(w), "ap_ci": _interval(boot[n]["ap"]),
            "auc_ipcw": r.auc(iw), "auc_ipcw_ci": _interval(boot[n]["auc_ipcw"]),
            "ap_ipcw": r.average_precision(iw), "ap_ipcw_ci": _interval(boot[n]["ap_ipcw"]),
        }
        if drive_level:
            # the point estimate averages 20 draws of one snapshot per drive (the same
            # 20 draws for every model)
            draws = [weighted_auc(s[p], y[p], dw[p]) for p in point_picks]
            row["auc_drive"] = float(np.nanmean(draws)) if np.isfinite(draws).any() else None
            row["auc_drive_ci"] = _interval(boot[n]["auc_drive"])
        out[n] = row
    return out, gains


def discrimination(test, D, models, horizons, reference, rounds, seed, log, retained=None):
    rows, diffs, skipped = [], [], {}
    retained = [] if retained is None else retained
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
        if reference in res and {"hazard_nosmart", "hazard_nocritical"} <= set(gains):
            # share of the SMART gain over the no-SMART model that the model without the
            # critical counters keeps: (nocritical - nosmart) / (reference - nosmart), per
            # paired bootstrap round
            full, kept = gains["hazard_nosmart"]["auc"], gains["hazard_nocritical"]["auc"]
            point_full = res[reference]["auc"] - res["hazard_nosmart"]["auc"]
            point_kept = res["hazard_nocritical"]["auc"] - res["hazard_nosmart"]["auc"]
            retained.append({
                "horizon": H, "share": point_kept / point_full if point_full else None,
                "share_ci": _interval([(a - b) / a for a, b in zip(full, kept, strict=True)
                                       if a])})
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


def slices(test, D, models, horizons, binary_horizon, rounds, seed, cfg, log,
           firmware_model=None):
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
    vendor, model = firmware_vendor(test, firmware_model) if firmware_model else (None, None)
    if vendor is not None:
        population[f"vendor {vendor} without {firmware_model}"] = (
            (test["vendor"] == vendor).to_numpy() & ~model)
    out = []
    for H in horizons:
        status = known_status(D.d, D.e, H)
        todo = dict(positive_side)
        if H == binary_horizon:
            todo.update(population)
        clean = ~test["critical_nonzero"].to_numpy().astype(bool)
        todo["silent failures vs negatives with no critical counter"] = silent
        for name, keep in todo.items():
            if name == "silent failures vs negatives with no critical counter":
                mask = ((status == 0) & clean) | keep
            else:
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
    year = pd.to_datetime(test["date"]).dt.year.to_numpy()
    # drives that do not fail in the test period, and their test snapshots
    quiet = ~D.fails
    quiet_rows = quiet[D.codes]
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
            quiet_alerted = np.zeros(D.n, dtype=bool)
            np.logical_or.at(quiet_alerted, D.codes[quiet_rows], alert[quiet_rows])

            def stats(w, drive_counts, alert=alert, any_alert=any_alert,
                      early_alert=early_alert, quiet_alerted=quiet_alerted):
                tp, fp = np.sum(w[alert & positive]), np.sum(w[alert & healthy])
                unk = np.sum(w[alert & unknown])
                f = drive_counts[failing_drives]
                qw = (drive_counts * D.weight_of_drive)[quiet]
                quiet_hit = np.sum(qw * quiet_alerted[quiet])
                caught = np.sum(f * any_alert[failing_drives])
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
                    # per drive: drives that never fail in the test period with at least
                    # one alert on their (weekly) test snapshots, and how many of them
                    # come with each failing drive alerted in its last `horizon` days
                    "share_nonfailing_drives_alerted":
                        float(quiet_hit / qw.sum()) if qw.sum() > 0 else None,
                    "nonfailing_alerted_per_failing_alerted":
                        float(quiet_hit / caught) if caught > 0 else None,
                }

            point = stats(D.w, np.ones(D.n))
            boot = [stats(D.w * c[D.codes], c) for c in counts_list]
            by_year = {}
            for yr in np.unique(year):
                h = healthy & (year == yr)
                if h.any():
                    by_year[str(int(yr))] = float(np.sum(D.w[alert & h]) / np.sum(D.w[h]))
            row = {"model": name, "horizon": horizon, "budget": rate, "threshold": float(threshold),
                   "false_alarm_rate_test_by_year": by_year,
                   "false_alarm_rate_val":
                       float(np.sum(w_val[healthy_val] * (s_val[healthy_val] >= threshold))
                             / np.sum(w_val[healthy_val])),
                   "failing_drives": int(failing_drives.size),
                   "failing_drives_alerted": int(any_alert[failing_drives].sum()),
                   "failing_drives_alerted_early": int(early_alert[failing_drives].sum()),
                   "nonfailing_drives": int(quiet.sum()),
                   "nonfailing_drives_alerted": int(quiet_alerted[quiet].sum()),
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


def on_stride(frame: pd.DataFrame, stride: int) -> np.ndarray:
    """Rows on their drive's stride days: the weekly schedule every drive is sampled on
    (panel._register_cohort's offsets). Near a failure the snapshot step keeps every
    day; these rows are the ones a weekly check would have seen."""
    serials, codes = np.unique(frame["serial_number"].to_numpy(), return_inverse=True)
    offset = np.array([int(stable_unit(s, "stride") * stride) for s in serials])
    days = (pd.to_datetime(frame["date"]) - pd.Timestamp("2000-01-01")).dt.days.to_numpy()
    return (days + offset[codes]) % stride == 0


def weekly_alerts(val, test, D, models, horizon, rates, stride, targets, rounds, seed,
                  pair=("hazard_smart", "rule_counters")):
    """Alerts per drive on a common weekly schedule.

    alerting() counts failing drives on their daily snapshots before failure and
    non-failing drives on weekly ones, so its per-drive figures mix two schedules. Here
    only stride-day snapshots count, for every drive: a failing drive is caught if one of
    them in its last `horizon` days alerts, a non-failing drive is a false alarm if any of
    its test-period ones alerts. Failing drives with no stride day in that window are left
    out (they could not be checked).

    budgets: the validation thresholds of alerting(). matched: for each target share of
    non-failing drives alerted, each model's threshold is set on test so that it alerts
    that share, and the share of failing drives caught is compared (a point on a
    drive-level ROC curve); the pair's difference gets a paired bootstrap interval.
    """
    week = on_stride(test, stride)
    st_val = known_status(val["duration_days"].to_numpy(), val["event"].to_numpy(), horizon)
    healthy_val, w_val = st_val == 0, val["weight"].to_numpy()
    quiet = ~D.fails
    window = week & (D.e == 1) & (D.d < horizon)
    failing = np.unique(D.codes[window])
    qrows = week & quiet[D.codes]
    dw = D.weight_of_drive
    counts_list = list(D.boot(rounds, seed))

    def drive_max(score, rows):
        out = np.full(D.n, -np.inf)
        np.maximum.at(out, D.codes[rows], score[rows])
        return out

    maxima, budgets = {}, []
    for name, info in models.items():
        s_val, s = score_of(val, name, info, horizon), score_of(test, name, info, horizon)
        if s_val is None:
            continue
        qmax, fmax = drive_max(s, qrows)[quiet], drive_max(s, window)[failing]
        maxima[name] = (qmax, fmax)
        for rate in rates:
            t = weighted_quantile_threshold(s_val[healthy_val], w_val[healthy_val], rate)

            def stats(c, t=t, qmax=qmax, fmax=fmax):
                qw, fw = (c * dw)[quiet], c[failing].astype(float)
                hit, false = np.sum(fw * (fmax >= t)), np.sum(qw * (qmax >= t))
                return (float(hit / fw.sum()), float(false / qw.sum()),
                        float(false / hit) if hit > 0 else np.nan)

            point = stats(np.ones(D.n))
            boot = [stats(c) for c in counts_list]
            budgets.append({
                "model": name, "budget": rate, "threshold": float(t),
                "failing_drives": int(failing.size),
                "failing_drives_alerted": int((fmax >= t).sum()),
                "share_failing_drives_alerted": point[0],
                "share_failing_drives_alerted_ci": _interval([b[0] for b in boot]),
                "share_nonfailing_drives_alerted": point[1],
                "share_nonfailing_drives_alerted_ci": _interval([b[1] for b in boot]),
                "nonfailing_alerted_per_failing_alerted": point[2],
                "nonfailing_alerted_per_failing_alerted_ci": _interval([b[2] for b in boot]),
            })

    # first alert: every drive counted once over the test period; a failing drive is
    # caught if any of its weekly checks before the failure alerts (any lead time), the
    # same span over which a non-failing drive can raise its one false alarm
    any_rows = week & (D.e == 1)
    failing_any = np.unique(D.codes[any_rows])
    first = {}
    for name in maxima:
        s = score_of(test, name, models[name], horizon)
        fmax = np.full(D.n, -np.inf)
        np.maximum.at(fmax, D.codes[any_rows], s[any_rows])
        first[name] = (maxima[name][0], fmax[failing_any])

    def caught(name, c, target, table=None, pos=None):
        qmax, fmax = (table or maxima)[name]
        pos = failing if pos is None else pos
        qw, fw = (c * dw)[quiet], c[pos].astype(float)
        t = weighted_quantile_threshold(qmax, qw, target)
        return (float(np.sum(fw * (fmax >= t)) / fw.sum()),
                float(np.sum(qw * (qmax >= t)) / qw.sum()))

    def compare(table, pos, shares=targets):
        out = []
        for target in shares:
            boot = {n: [caught(n, c, target, table, pos) for c in counts_list] for n in table}
            for name in table:
                share, achieved = caught(name, np.ones(D.n), target, table, pos)
                row = {"model": name, "target_nonfailing_share": target,
                       "nonfailing_share": achieved, "share_failing_drives_alerted": share,
                       "share_failing_drives_alerted_ci": _interval([b[0] for b in boot[name]])}
                if name != pair[1] and pair[1] in table:
                    base = caught(pair[1], np.ones(D.n), target, table, pos)[0]
                    row["versus"] = pair[1]
                    row["difference"] = share - base
                    row["difference_ci"] = _interval([a[0] - b[0] for a, b in
                                                      zip(boot[name], boot[pair[1]], strict=True)])
                if name not in pair and pair[0] in table:
                    base = caught(pair[0], np.ones(D.n), target, table, pos)[0]
                    row["difference_vs_reference"] = share - base
                    row["difference_vs_reference_ci"] = _interval(
                        [a[0] - b[0] for a, b in zip(boot[name], boot[pair[0]], strict=True)])
                out.append(row)
        return out

    matched = compare(maxima, failing)
    matched_first_alert = compare(first, failing_any)
    # how early the first alert of each caught failing drive came: the largest days to
    # failure among its alerted weekly checks, at the point-estimate threshold
    for row in matched_first_alert:
        name = row["model"]
        qmax = first[name][0]
        t = weighted_quantile_threshold(qmax, dw[quiet], row["target_nonfailing_share"])
        s = score_of(test, name, models[name], horizon)
        hit = any_rows & (s >= t)
        lead = np.full(D.n, -1.0)
        np.maximum.at(lead, D.codes[hit], D.d[hit].astype(float))
        lead = lead[failing_any]
        lead = lead[lead >= 0]
        if lead.size:
            row["first_alert_lead_days_quartiles"] = [float(q) for q in
                                                      np.percentile(lead, [25, 50, 75])]
            row["share_caught_first_alerted_within_horizon"] = float(np.mean(lead < horizon))
    # the operator's criterion: any critical counter above zero, i.e. the rule's score > 0
    # (it is a sum of log1p counters). Its own point, and the models at its share of
    # non-failing drives alerted.
    any_counter = None
    if pair[1] in maxima:
        qr, fr = maxima[pair[1]]
        fr_any = first[pair[1]][1]

        def zero_point(c):
            qw = (c * dw)[quiet]
            fw, fa = c[failing].astype(float), c[failing_any].astype(float)
            return (float(np.sum(qw * (qr > 0)) / qw.sum()),
                    float(np.sum(fw * (fr > 0)) / fw.sum()),
                    float(np.sum(fa * (fr_any > 0)) / fa.sum()))

        point = zero_point(np.ones(D.n))
        boot = [zero_point(c) for c in counts_list]

        def at_zero(table, pos, k):
            """Each model at the share of non-failing drives the rule alerts at score > 0,
            that share recomputed in every resample, against the rule at score > 0 (k
            picks the rule's caught share: 1 = last `horizon` days, 2 = any lead)."""
            out = []
            for name in table:
                if name == pair[1]:
                    continue
                share = caught(name, np.ones(D.n), point[0], table, pos)
                diffs = [caught(name, c, b[0], table, pos)[0] - b[k]
                         for c, b in zip(counts_list, boot, strict=True)]
                row = {"model": name, "nonfailing_share": share[1],
                       "share_failing_drives_alerted": share[0],
                       "versus": pair[1] + " > 0", "difference": share[0] - point[k],
                       "difference_ci": _interval(diffs)}
                if name != pair[0] and pair[0] in table:
                    ref = caught(pair[0], np.ones(D.n), point[0], table, pos)[0]
                    row["difference_vs_reference"] = share[0] - ref
                    row["difference_vs_reference_ci"] = _interval(
                        [caught(name, c, b[0], table, pos)[0]
                         - caught(pair[0], c, b[0], table, pos)[0]
                         for c, b in zip(counts_list, boot, strict=True)])
                out.append(row)
            return out

        any_counter = {
            "share_nonfailing_drives_alerted": point[0],
            "share_nonfailing_drives_alerted_ci": _interval([b[0] for b in boot]),
            "share_failing_drives_alerted": point[1],
            "share_failing_drives_alerted_ci": _interval([b[1] for b in boot]),
            "share_failing_drives_alerted_any_lead": point[2],
            "share_failing_drives_alerted_any_lead_ci": _interval([b[2] for b in boot]),
            "matched": at_zero(maxima, failing, 1),
            "matched_first_alert": at_zero(first, failing_any, 2),
        }
    return {"stride_days": stride, "failing_drives_checked": int(failing.size),
            "any_critical_counter": any_counter,
            "failing_drives_total": int(np.unique(D.codes[(D.e == 1) & (D.d < horizon)]).size),
            "nonfailing_drives": int(quiet.sum()), "budgets": budgets, "matched": matched,
            "failing_drives_any_lead": int(failing_any.size),
            "matched_first_alert": matched_first_alert}


def validation_discrimination(val, models, horizons):
    """ROC-AUC and PR-AUC on the validation drives (2016-2023, known-status snapshots), the
    numbers a choice made without the test set would rest on: e.g. which training-weight
    exponent to keep. Point estimates only."""
    d, e, w = (val[c].to_numpy() for c in ("duration_days", "event", "weight"))
    rows = []
    for h in horizons:
        st = known_status(d, e, h)
        mask = st >= 0
        y = st[mask]
        if y.size == 0 or y.min() == y.max():
            continue
        for name, info in models.items():
            s = score_of(val, name, info, h)
            if s is None:
                continue
            rows.append({"model": name, "horizon": h,
                         "auc": weighted_auc(s[mask], y, w[mask]),
                         "ap": weighted_average_precision(s[mask], y, w[mask]),
                         "snapshots": int(mask.sum()), "positives": int(y.sum())})
    return rows


def windowed_alerts(test, D, models, horizon, stride, targets, rounds, seed, freq,
                    pair=("hazard_smart", "rule_counters")):
    """Per-drive alerts counted per calendar window (quarter "Q" or year "Y").

    weekly_alerts() counts a non-failing drive as alerted if any of its weekly checks over
    the whole test period fires, but a failing drive only on its checks in the last
    `horizon` days; a score that only accumulates (the counter rule) gains from that. Here
    the unit is a drive in one window. A negative unit is a drive with weekly snapshots in
    the window that does not fail in it nor within `horizon` days after it; its score is
    its highest weekly score in the window. A positive unit is a failing drive in the
    window where it fails, scored on its weekly snapshots of the last `horizon` days
    (weekly_alerts' rule). Units of a drive that fails within `horizon` days after a window
    are left out of that window. At each target share of negative units alerted, each
    model's threshold is set on test and the share of positive units caught is compared,
    with a paired drive bootstrap for the pair.
    """
    week = on_stride(test, stride)
    date = pd.to_datetime(test["date"])
    period = date.dt.to_period(freq)
    ends = period.dt.end_time.dt.normalize().to_numpy()
    fail_day = np.full(D.n, np.datetime64("NaT", "ns"))
    ev = D.e == 1
    fail_day[D.codes[ev]] = (date[ev] + pd.to_timedelta(D.d[ev], unit="D")).to_numpy()
    fd = fail_day[D.codes]
    clear = np.isnat(fd) | (fd > ends + np.timedelta64(horizon, "D"))
    neg_rows = week & clear
    pos_rows = week & ev & (D.d < horizon)
    neg_key = pd.MultiIndex.from_arrays([D.codes[neg_rows], period[neg_rows].astype(str)])
    neg_units = neg_key.drop_duplicates()
    neg_drive = neg_units.get_level_values(0).to_numpy()
    pos_drive = np.unique(D.codes[pos_rows])
    counts_list = list(D.boot(rounds, seed))
    dw = D.weight_of_drive

    maxima = {}
    for name, info in models.items():
        s = score_of(test, name, info, horizon)
        if s is None:
            continue
        qmax = pd.Series(s[neg_rows], index=neg_key).groupby(level=[0, 1]).max()
        qmax = qmax.reindex(neg_units).to_numpy()
        fmax = np.full(D.n, -np.inf)
        np.maximum.at(fmax, D.codes[pos_rows], s[pos_rows])
        maxima[name] = (qmax, fmax[pos_drive])

    def caught(name, c, target):
        qmax, fmax = maxima[name]
        qw, fw = (c * dw)[neg_drive], c[pos_drive].astype(float)
        t = weighted_quantile_threshold(qmax, qw, target)
        return (float(np.sum(fw * (fmax >= t)) / fw.sum()),
                float(np.sum(qw * (qmax >= t)) / qw.sum()))

    rows = []
    for target in targets:
        boot = {n: [caught(n, c, target) for c in counts_list] for n in maxima}
        for name in maxima:
            share, achieved = caught(name, np.ones(D.n), target)
            row = {"window": freq, "model": name, "target_nonfailing_share": target,
                   "nonfailing_share": achieved, "share_failing_drives_alerted": share,
                   "share_failing_drives_alerted_ci": _interval([b[0] for b in boot[name]])}
            if name != pair[1] and pair[1] in maxima:
                row["versus"] = pair[1]
                row["difference"] = share - caught(pair[1], np.ones(D.n), target)[0]
                row["difference_ci"] = _interval([a[0] - b[0] for a, b in
                                                  zip(boot[name], boot[pair[1]], strict=True)])
            if name not in pair and pair[0] in maxima:
                row["difference_vs_reference"] = (share
                                                  - caught(pair[0], np.ones(D.n), target)[0])
                row["difference_vs_reference_ci"] = _interval(
                    [a[0] - b[0] for a, b in zip(boot[name], boot[pair[0]], strict=True)])
            rows.append(row)
    return {"window": freq, "negative_units": int(len(neg_units)),
            "negative_units_of_drives_failing_later": int(D.fails[neg_drive].sum()),
            "positive_units": int(pos_drive.size), "matched": rows}


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
    all_counts = list(D.boot(rounds, seed))     # the same resamples for every model
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
                def one_round(k, risk=r):   # bind this loop's score (ruff B023)
                    wb = D.w * all_counts[k][D.codes]
                    return (concordance(risk, D.d, D.e, wb),
                            uno_concordance(risk, D.d, D.e, wb, tau, D.G))

                res = parallel_rounds(one_round, len(all_counts))
                h, u = (list(x) for x in zip(*res, strict=True)) if res else ([], [])
                row["harrell_ci"], row["uno_ci"] = _interval(h), _interval(u)
            out.append(row)
    log(f"concordance on {len(sample)} rows of {D.n} drives")
    return out, len(sample), D.n


def quantile_calibration(d, e, w, t, G=None) -> tuple[float | None, float | None, int]:
    """Weighted share of snapshots that failed before their predicted day t.

    For a calibrated q-quantile the share should be about q. "Failed before t" is a
    failure on a day d < t. Day conventions follow known_status: a snapshot censored on day
    d is seen alive through day d, so it is known not to have failed before t once
    d >= ceil(t) - 1; a failure on a day >= t is known too.

    Returns (known-outcome share, IPCW share, snapshots with a known outcome). The
    known-outcome share drops snapshots censored before their outcome is known; those
    tend to have a late t and a low chance of failing by it, so the share leans high.
    The IPCW share weights a failure on day d by 1 / G(d) and a known survivor by
    1 / G(ceil(t) - 1), as ipcw_weights does for a fixed horizon, then normalizes.

    G is one Kaplan-Meier curve of the censoring time for all snapshots. The IPCW share
    is therefore unbiased only if censoring is independent of both the failure time and
    the predicted day. Here most censoring is the panel's end, so it depends on the
    snapshot date, and predicted days can depend on the date too (drift): read the IPCW
    share as a censoring-adjusted estimate under that assumption, not an exact one.
    Neither share corrects for retirement related to health.
    """
    d = np.asarray(d)
    e = np.asarray(e) == 1
    w = np.asarray(w, dtype=float)
    finite = np.isfinite(t)
    last = np.ceil(np.where(finite, t, 0)) - 1   # last whole day before t
    failed = finite & e & (d < t)
    survived = finite & ~failed & ((e & (d >= t)) | (~e & (d >= last)))
    known = failed | survived
    if not known.any():
        return None, None, 0
    share = float(np.sum(w[failed]) / np.sum(w[known]))
    G = censoring_survival(d, e, w) if G is None else G
    wf = w[failed] / np.maximum(G(d[failed]), 1e-12)
    ws = w[survived] / np.maximum(G(last[survived]), 1e-12)
    return share, float(wf.sum() / (wf.sum() + ws.sum())), int(known.sum())


def life(test, models, edges, D=None, rounds=0, seed=0) -> tuple[list[dict], pd.DataFrame]:
    """Remaining-life estimates: are the predicted days right, and how early is a failure
    visible?

    With D and rounds, the headline shares and the mean error get drive-bootstrap intervals
    (`<key>_ci`), resampling drives as discrimination() does; the censoring curve G stays
    fixed, as in the other IPCW intervals."""
    summary, table = [], []
    counts_list = list(D.boot(rounds, seed)) if D is not None and rounds else []
    d, e, w = (test[c].to_numpy() for c in ("duration_days", "event", "weight"))
    status = known_status(d, e, edges[-1])
    G = censoring_survival(d, e == 1, w)
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
            share, share_ipcw, n = quantile_calibration(d, e, w, col, G)
            qcal[str(q)] = {"target": q, "share_failed_by_predicted_day": share,
                            "share_failed_by_predicted_day_ipcw": share_ipcw, "snapshots": n}
        boot_ci = {}
        if counts_list:
            def one_round(i, med=med, q10=q10, q90=q90, covered=covered, finite=finite,
                          fails=fails):
                wb = w * counts_list[i][D.codes]

                def bmean(x, keep):
                    tot = np.sum(wb[keep])
                    return float(np.sum(wb[keep] * x[keep]) / tot) if tot > 0 else np.nan

                out = {"share_median_within_horizon": bmean(finite.astype(float), fails),
                       "median_abs_error_days": bmean(np.abs(med - d), fails & finite),
                       "interval_q10_q90_coverage": bmean(covered.astype(float), fails)}
                for q, col in ((0.1, q10), (0.5, med), (0.9, q90)):
                    share, share_ipcw, _ = quantile_calibration(d, e, wb, col, G)
                    out[f"q{q}"], out[f"q{q}_ipcw"] = share, share_ipcw
                return out

            res = parallel_rounds(one_round, len(counts_list))
            boot_ci = {k: _interval([r[k] for r in res if r[k] is not None]) for k in res[0]}
            for q in ("0.1", "0.5", "0.9"):
                qcal[q]["share_failed_by_predicted_day_ci"] = boot_ci.pop(f"q{q}")
                qcal[q]["share_failed_by_predicted_day_ipcw_ci"] = boot_ci.pop(f"q{q}_ipcw")
        summary.append({
            "model": name,
            "quantile_calibration": qcal,
            **{f"{k}_ci": v for k, v in boot_ci.items()},
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


def firmware_vendor(frame: pd.DataFrame, firmware_model: str) -> tuple[str | None, np.ndarray]:
    """(vendor of firmware_model, row mask of that model). Model names are matched as
    substrings, since the panel prefixes some of them with the vendor."""
    model = frame["model"].fillna("").str.contains(firmware_model, regex=False).to_numpy()
    vendors = frame.loc[model, "vendor"].dropna()
    return (vendors.mode().iloc[0] if not vendors.empty else None), model


def full_follow_up(test, D, models, horizons, reference, rounds, seed, log):
    """Ranking metrics on the snapshots that the panel could follow for a whole horizon.

    The main estimator keeps every snapshot whose status at H is known, so a failure a
    few days before the panel's end counts as a positive while the healthy snapshots of
    the same days are unknown and dropped. That lifts the positive share at long
    horizons. Here a snapshot counts only if it is dated at least H - 1 days before the
    panel's last day, for positives and negatives alike. Drives retired without failing
    inside the horizon are still unknown (and IPCW-weighted in the _ipcw columns): this
    removes the administrative asymmetry, not informative retirement.
    """
    date = pd.to_datetime(test["date"])
    room = (pd.to_datetime(test["last_date"]).max() - date).dt.days.to_numpy()
    rows, diffs = [], []
    for H in horizons:
        keep = room >= H - 1
        res, gains = _ranking_metrics(test, D, models, H, keep, rounds, seed + H, reference)
        if res is None:
            continue
        observed = km_failure(D.d[keep], D.e[keep], D.w[keep], H)
        last = date[keep].max()
        for n, r in res.items():
            rows.append({"horizon": H, "model": n, "last_snapshot_date": str(last.date()),
                         "observed_km": observed, **r})
        if reference in res:
            for n, g in gains.items():
                diffs.append({"horizon": H, "reference": reference, "other": n,
                              "auc_gain": res[reference]["auc"] - res[n]["auc"],
                              "auc_gain_ci": _interval(g["auc"]),
                              "ap_gain": res[reference]["ap"] - res[n]["ap"],
                              "ap_gain_ci": _interval(g["ap"])})
        log(f"full follow-up at {H} days: {int(keep.sum())} snapshots up to {last.date()}")
    return rows, diffs


def _groups(frame, cap_split_tb, firmware_model, known_models=None):
    """{group name: row mask} for calibration_by_group and composition. known_models: the
    drive models the model_code feature names (the most frequent in training); the rest
    share one "other" category."""
    cap = frame["capacity_bytes"].to_numpy() / 1e12
    out = {"all": np.ones(len(frame), dtype=bool),
           f"capacity >= {cap_split_tb} TB": cap >= cap_split_tb,
           f"capacity < {cap_split_tb} TB": cap < cap_split_tb}
    for v in sorted(frame["vendor"].dropna().unique()):
        out[f"vendor {v}"] = (frame["vendor"] == v).to_numpy()
    if "first_date" in frame:
        # time since the drive first appears in the panel (its age for drives that
        # arrive after the panel starts)
        age = (pd.to_datetime(frame["date"]) - pd.to_datetime(frame["first_date"])).dt.days
        age = age.to_numpy() / 365.25
        out["in service < 2 years"] = age < 2
        out["in service 2-4 years"] = (age >= 2) & (age < 4)
        out["in service >= 4 years"] = age >= 4
    if known_models:
        known = frame["model"].isin(known_models).to_numpy()
        out["training models"] = known
        out["other models"] = ~known
        if "first_date" in frame:
            out["in service < 2 years, training models"] = (age < 2) & known
            out["in service < 2 years, other models"] = (age < 2) & ~known
    vendor, model = firmware_vendor(frame, firmware_model) if firmware_model else (None, None)
    if vendor is not None:
        out[f"model {firmware_model}"] = model
        out[f"vendor {vendor} without {firmware_model}"] = (
            (frame["vendor"] == vendor).to_numpy() & ~model)
    return out


def calibration_by_group(preds, name, H, cap_split_tb, firmware_model, rounds, seed,
                         known_models=None):
    """Predicted vs Kaplan-Meier observed H-day risk of one model per split, calendar year
    and group, with a drive-bootstrap interval for the ratio. Tells whether a drift in
    calibration sits in one part of the fleet (large drives, one vendor, one model)."""
    rows = []
    year = pd.to_datetime(preds["date"]).dt.year
    for (split, yr), g in preds.groupby([preds["split"], year]):
        for group, m in _groups(g, cap_split_tb, firmware_model, known_models).items():
            if not m.any():
                continue
            sub = g[m]
            d, e, w = (sub[c].to_numpy() for c in ("duration_days", "event", "weight"))
            p = sub[f"{name}__p{H}"].to_numpy()
            codes, uniques = pd.factorize(sub["serial_number"])
            pred, obs = float(np.average(p, weights=w)), km_failure(d, e, w, H)
            boot = []
            for counts in bootstrap_drive_counts(len(uniques), rounds, seed + int(yr)):
                wb = w * counts[codes]
                ob = km_failure(d, e, wb, H)
                boot.append(np.sum(wb * p) / np.sum(wb) / ob if ob > 0 else np.nan)
            failing = int(sub.loc[sub["event"] == 1, "serial_number"].nunique())
            rows.append({"split": split, "year": int(yr), "group": group, "model": name,
                         "horizon": H, "snapshots": int(m.sum()), "drives": len(uniques),
                         "failing_drives": failing,
                         "predicted": pred, "observed_km": obs,
                         "ratio": pred / obs if obs > 0 else None, "ratio_ci": _interval(boot)})
    return rows


def composition(preds, cap_split_tb, firmware_model, known_models=None):
    """Weighted share of snapshots per group, split and calendar year (fleet mix)."""
    rows = []
    year = pd.to_datetime(preds["date"]).dt.year
    for (split, yr), g in preds.groupby([preds["split"], year]):
        w = g["weight"].to_numpy()
        for group, m in _groups(g, cap_split_tb, firmware_model, known_models).items():
            if group != "all":
                rows.append({"split": split, "year": int(yr), "group": group,
                             "weight_share": float(w[m].sum() / w.sum())})
    return rows


def seed_spread(test, D, models, seeds, horizons, pair=("hazard_smart", "binary_30d")):
    """Point ROC-AUC and PR-AUC of each seed replicate and of the model it replicates,
    on the known-status snapshots of each horizon; plus the survival-minus-classifier
    difference for each seed pair (the original pair is seed 0)."""
    family = {}
    for n in seeds:
        hit = SEED.match(n)
        family.setdefault(hit["family"], {0: hit["family"]})[int(hit["k"])] = n
    rows, diffs = [], []
    allm = {**models, **seeds}
    for fam, members in family.items():
        if fam not in models:
            continue
        for H in horizons:
            status = known_status(D.d, D.e, H)
            m = status >= 0
            y, w = status[m], D.w[m]
            for k, n in sorted(members.items()):
                s = score_of(test, n, allm[n], H)
                if s is None:
                    continue
                r = RankedScores(s[m], y)
                rows.append({"family": fam, "seed_index": k, "model": n, "horizon": H,
                             "auc": r.auc(w), "ap": r.average_precision(w)})
    a, b = pair
    if a in family and b in family:
        by = {(r["model"], r["horizon"]): r for r in rows}
        for k in sorted(set(family[a]) & set(family[b])):
            for H in horizons:
                ra, rb = by.get((family[a][k], H)), by.get((family[b][k], H))
                if ra and rb:
                    diffs.append({"seed_index": k, "horizon": H, "survival": family[a][k],
                                  "classifier": family[b][k], "auc_diff": ra["auc"] - rb["auc"],
                                  "ap_diff": ra["ap"] - rb["ap"]})
    summary = []
    df = pd.DataFrame(rows)
    if not df.empty:
        for (fam, H), g in df.groupby(["family", "horizon"]):
            summary.append({"family": fam, "horizon": int(H), "replicates": len(g),
                            **{f"{k}_{f}": float(getattr(g[k], f)())
                               for k in ("auc", "ap") for f in ("min", "max", "mean", "std")}})
    return {"rows": rows, "summary": summary, "pair_differences": diffs}


def evaluate(ctx):
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    ev, label = study["evaluation"], study["label"]
    edges, H = label["bin_edges"], label["binary_horizon"]
    preds = pd.read_parquet(ctx.inputs["predictions"])
    cohort = pd.read_parquet(ctx.inputs["cohort"], columns=COHORT_COLUMNS)
    cohort["left_truncated"] = left_truncated(cohort["first_date"])
    preds = preds.merge(cohort, on="serial_number", how="left", validate="many_to_one")
    models, seeds = split_seeds(discover(preds.columns))
    reference = ctx.params["reference"]
    firmware = ctx.params.get("firmware_model")
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

    retained = []
    disc, diffs, skipped = discrimination(test, D, models, label["horizons"], reference,
                                          rounds, seed, log, retained)
    slice_rows = slices(test, D, models, label["horizons"], H, rounds, seed, ev, log, firmware)
    follow_rows, follow_diffs = full_follow_up(test, D, models, label["horizons"], reference,
                                               rounds, seed, log)

    conc, conc_rows, conc_drives = concordance_table(
        test, models, ctx.params.get("concordance_max_rows", 300_000),
        ev.get("concordance_bootstrap_rounds", rounds), seed, edges[-1], H, log)

    calib = calibration(test, models, label["horizons"])
    rates = sorted(set(ev.get("alert_false_alarm_rates", [])) | {ev["alert_false_alarm_rate"]})
    alerts, detection = alerting(val_cal, test, D, models, H, rates, ev["alert_false_alarm_rate"],
                                 ev["min_lead_days"], edges, rounds, seed)
    stride = load_sample(ctx.inputs["sample"])["stride_days"]
    targets = ev.get("matched_nonfailing_shares", [0.01, 0.025, 0.05])
    # the seed replicates join the per-drive comparisons, to show how far their verdicts
    # move with the training seed
    every = {**models, **seeds}
    weekly = weekly_alerts(val_cal, test, D, every, H, rates, stride, targets, rounds, seed)
    weekly["per_window"] = [windowed_alerts(test, D, every, H, stride, targets, rounds, seed, f)
                            for f in ("Q", "Y")]
    log("alerting done")
    life_summary, life_table = life(test, models, edges, D, rounds, seed)
    cal_rows = calibration_in_the_large(preds, models, label["horizons"], H, rounds, seed)
    thresholds = {a["model"]: a["threshold"] for a in alerts
                  if a["budget"] == ev["alert_false_alarm_rate"]}
    retire = retirement(preds, models, H, thresholds)
    log("calibration over time and retirement done")
    known = None
    if "schema" in ctx.inputs:
        levels = json.loads(ctx.inputs["schema"].read_text())["categorical"]["model_code"]
        known = [m for m in levels if m != "other"]
    by_group = calibration_by_group(preds, reference, H, ev["capacity_split_tb"], firmware,
                                    rounds, seed, known)
    mix = composition(preds, ev["capacity_split_tb"], firmware, known)
    spread = seed_spread(test, D, models, seeds, label["horizons"])
    log(f"calibration by group done; {len(seeds)} seed replicates")

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
        "full_follow_up": follow_rows,
        "full_follow_up_gain": follow_diffs,
        "calibration_by_group": by_group,
        "composition": mix,
        "seed_spread": spread,
        "weekly_alerts": weekly,
        "validation_discrimination": validation_discrimination(
            val, {**models, **seeds}, label["horizons"]),
        "gain_retained_without_critical_counters": retained,
    })
    main = next(c for c in conc if c["model"] == reference)
    return {f"auc{H}_{reference}": _row(disc, H, reference)["auc"],
            f"c_{reference}": main["harrell"]}

"""Write the run's report to build/report from the evaluation outputs.

- results.md: the run (scale, cohort, test set, gate) and the headline numbers in a few
  compact tables, each with one line on how to read it.
- analysis.md: the plain-language answer and every detailed table, with the figures.

Every sentence that states a conclusion is derived from the numbers (for example, "SMART
adds information" only if the bootstrap interval of the gain excludes zero), so the
report cannot drift from the results the way v2's hand-written claims did.
"""

from __future__ import annotations

import json
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CORE = ["hazard_smart", "hazard_nosmart", "binary_30d", "rule_counters"]
ABLATIONS = ["hazard_nocritical", "hazard_usage", "hazard_smart_w075", "hazard_smart_w100",
             "hazard_smart_recent"]
WHY = {
    "hazard_nocritical": "drops counters 5, 187, 188, 197 and 198 (raw, normalized and "
                         "trends), the ones behind Backblaze's own replacement decisions. A "
                         "drive replaced because these counters rose is recorded as failed, so "
                         "part of the full model's SMART signal may be the replacement policy "
                         "itself; the full model's gain over context only is an upper bound on "
                         "what SMART adds beyond that policy.",
    "hazard_usage": "context plus the usage counters only (4, 9, 12, 193, 240-242: power-on "
                    "hours, start/stop and power cycles, load cycles, head flying hours, LBAs "
                    "written and read). Tests whether SMART helps only because it measures "
                    "age and wear.",
    "hazard_smart_w075": "the reference features with training weights to the power 0.75 "
                         "instead of 0.5. Tests how much the ranking depends on the weight "
                         "exponent.",
    "hazard_smart_w100": "the same with the full inverse-probability weights (power 1.0).",
    "hazard_smart_recent": "the reference trees with probabilities recalibrated on the last "
                           "validation year before the training cutoff. Tests whether a recent "
                           "recalibration fixes drift (see Calibration over time); the trees "
                           "are the same, so ranking changes only through the per-bin "
                           "recalibration.",
}


def _finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and not math.isfinite(x))


def _fmt(x, digits=3):
    return f"{x:.{digits}f}" if _finite(x) else "n/a"


def _days(x):
    if x is None:
        return "n/a"
    return "> 1 year" if not math.isfinite(x) else f"{x:.0f}"


def _pct(x, digits=1):
    return f"{100 * x:.{digits}f}%" if _finite(x) else "n/a"


def _ci_ok(ci) -> bool:
    return bool(ci) and len(ci) == 2 and _finite(ci[0]) and _finite(ci[1])


def _ci(ci, digits=3):
    return f"[{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]" if _ci_ok(ci) else "n/a"


def est(x, ci=None, digits=3, pct=False, sign=False) -> str:
    """A value with its interval: "0.857 [0.837, 0.881]". `ci=None` means the metric has
    no interval (value only); an interval that could not be estimated shows as [n/a].
    `sign` puts a + on a positive point estimate (for differences)."""
    one = (lambda v: _pct(v, digits)) if pct else (lambda v: _fmt(v, digits))
    head = one(x)
    if sign and _finite(x) and x > 0:
        head = "+" + head
    if ci is None:
        return head
    return f"{head} [{one(ci[0])}, {one(ci[1])}]" if _ci_ok(ci) else f"{head} [n/a]"


def side(ci, at=0.0) -> int:
    """+1 if the interval lies above `at`, -1 if below, 0 if it covers it or is missing."""
    if not _ci_ok(ci):
        return 0
    return 1 if ci[0] > at else -1 if ci[1] < at else 0


def table(header: list[str], rows: list[list]) -> list[str]:
    """Markdown table lines; cells are str()-ed, None becomes "n/a"."""
    cell = lambda v: "n/a" if v is None else str(v)  # noqa: E731
    return (["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows])


def _label(name, labels):
    """The display name from the step's `labels` param, else the model name."""
    return labels.get(name, name)


def _rank(name):
    order = CORE + ABLATIONS
    return order.index(name) if name in order else len(order)


def _sorted(rows, *keys):
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys) + (_rank(r["model"]),))


def top_importance(gain: dict, n: int = 20) -> pd.Series:
    """The n features with the most gain, largest first, as shares of the total gain.

    The meta JSON is written with sorted keys, so the stored order is alphabetical and
    the ranking has to be redone here.
    """
    s = pd.Series(gain, dtype=float)
    total = s.sum()
    return (s / (total if total > 0 else 1.0)).sort_values(ascending=False).head(n)


def _binary_horizon(metrics) -> int:
    """The yes/no horizon: the binary model's, else the alerting horizon, else 30."""
    for info in metrics.get("models", {}).values():
        if info.get("kind") == "binary" and info.get("horizons"):
            return info["horizons"][0]
    return metrics["alerting"][0]["horizon"] if metrics.get("alerting") else 30


def _main_alert(metrics, ref):
    """The alerting row of the reference at the main false-alarm budget."""
    rows = metrics["alerting"]
    main = metrics.get("alert_false_alarm_rate")
    return next((a for a in rows if a["model"] == ref and a["budget"] == main),
                next((a for a in rows if a["budget"] == main), rows[0] if rows else None))


def figures(out, metrics, calib, detection, preds, meta_ref, ref, labels):
    disc = pd.DataFrame(metrics["discrimination"])
    disc = disc[disc["model"].isin(CORE)]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    models = sorted(dict.fromkeys(disc["model"]), key=_rank)
    hz = sorted(disc["horizon"].unique())
    for i, name in enumerate(models):
        d = disc[disc["model"] == name]
        x = np.array([hz.index(h) for h in d["horizon"]]) + (i - (len(models) - 1) / 2) * 0.12
        ci = [c if _ci_ok(c) else [a, a] for c, a in zip(d["auc_ci"], d["auc"], strict=True)]
        lo = d["auc"].to_numpy() - np.array([c[0] for c in ci])
        hi = np.array([c[1] for c in ci]) - d["auc"].to_numpy()
        ax.errorbar(x, d["auc"], yerr=[lo, hi], fmt="o", capsize=3, label=_label(name, labels))
    ax.set_xticks(range(len(hz)), [f"{h} d" for h in hz])
    ax.set_xlabel("horizon: fails within")
    ax.set_ylabel("ROC-AUC (95% drive bootstrap)")
    ax.axhline(0.5, color="grey", lw=0.8, ls="--")
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "auc_by_horizon.png", dpi=120)
    plt.close(fig)

    c = calib[calib["model"] == ref]
    if not c.empty:
        fig, ax = plt.subplots(figsize=(5.5, 5))
        for H, g in c.groupby("horizon"):
            ax.plot(g["predicted"], g["observed_km"], "o-", label=f"{H} days")
        lim = [max(1e-5, min(c["predicted"].min(), c["observed_km"].replace(0, np.nan).min())),
               max(c["predicted"].max(), c["observed_km"].max()) * 1.2]
        ax.plot(lim, lim, color="grey", ls="--", lw=0.8)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("predicted P(fail within horizon)")
        ax.set_ylabel("observed (Kaplan-Meier)")
        ax.set_title("Calibration by risk decile, test drives")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3, which="both")
        fig.tight_layout()
        fig.savefig(out / "calibration.png", dpi=120)
        plt.close(fig)

    shown = detection[detection["model"].isin(CORE + ["hazard_smart_recent"])] \
        if not detection.empty else detection
    main = _main_alert(metrics, ref)
    if not shown.empty and main:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        for name, g in shown.groupby("model", sort=False):
            ax.plot(g["days_before_failure"], g["alerted"], "o-", label=_label(name, labels))
        ax.set_xlabel("days before failure")
        ax.set_ylabel("share of failing-drive snapshots alerted")
        ax.set_ylim(0, 1)
        ax.set_title(f"Alerts at a {_pct(main['budget'], 0)} false-alarm budget "
                     "(set on validation)")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "detection.png", dpi=120)
        plt.close(fig)

    imp = top_importance(meta_ref["importance_gain"])[::-1]
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.barh(imp.index, imp)
    ax.set_xlabel("share of total gain (top 20)")
    ax.set_title(f"What the {ref} model uses")
    fig.tight_layout()
    fig.savefig(out / "importance.png", dpi=120)
    plt.close(fig)

    t = preds[(preds["split"] == "test") & (preds["event"] == 1) & (preds["duration_days"] < 365)]
    if len(t):
        med = t[f"{ref}__median_days"].to_numpy()
        shown = np.where(np.isfinite(med), med, 400)
        fig, ax = plt.subplots(figsize=(5.5, 5))
        ax.scatter(t["duration_days"], shown, s=4, alpha=0.3)
        ax.plot([0, 365], [0, 365], color="grey", ls="--", lw=0.8)
        ax.axhline(400, color="red", lw=0.6)
        ax.text(5, 405, "predicted > 365 days", fontsize=7, color="red")
        ax.set_xlabel("actual days to failure")
        ax.set_ylabel("predicted median remaining life (days)")
        ax.set_title("Remaining life, failing test drives")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "remaining_life.png", dpi=120)
        plt.close(fig)


def _follow_up_note(preds, disc_rows) -> str:
    """How the known-status rows shrink with the horizon, from the test predictions."""
    t = preds[preds["split"] == "test"]
    d, e = t["duration_days"].to_numpy(), t["event"].to_numpy() == 1
    date = pd.to_datetime(t["date"])
    parts = []
    for H in sorted({r["horizon"] for r in disc_rows}):
        healthy = (e & (d >= H)) | (~e & (d >= H - 1))
        last = date[healthy].max() if healthy.any() else None
        n = next(r["snapshots"] for r in disc_rows if r["horizon"] == H)
        parts.append(f"{H} d: {n} snapshots, known-healthy ones dated up to "
                     f"{last.date() if last is not None else 'n/a'}")
    longest = max(r["horizon"] for r in disc_rows)
    first_year = date.min().year if len(date) else "n/a"
    return ("A horizon of H days needs H days of follow-up to know that a drive survived it, "
            f"so the longer the horizon, the earlier the test snapshots it can use. The "
            f"{longest}-day row uses only snapshots from roughly the first test year "
            f"({first_year}); longer horizons are measured on an earlier, different calendar "
            "cohort than the short ones, so the rows are not a like-for-like trend. Test "
            f"snapshots with a known status ({len(t)} in total): " + "; ".join(parts) + ".")


def _drift_sentence(row, label) -> str:
    lo, hi = row["val_band"]
    outside = [t["year"] for t in row["test_years"] if t["outside_band"]]
    last = (f"The last validation year ({row['last_val_year']}, ratio "
            f"{_fmt(row['last_val_ratio'], 2)}) is "
            + ("outside" if row["last_val_year_outside_earlier_band"] else "inside")
            + " the band of the earlier validation years"
            + (", an early sign of drift that needs no test data." if
               row["last_val_year_outside_earlier_band"] else "."))
    test = (f"Test years outside the band: {', '.join(map(str, outside))}." if outside
            else "No test year falls outside the band.")
    return (f"- {label}: predicted/observed ratio over validation years spans "
            f"{_fmt(lo, 2)} to {_fmt(hi, 2)}. {last} {test}")


def report(ctx):
    out = ctx.outputs["dir"]
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        old.unlink()
    metrics = json.loads(ctx.inputs["metrics"].read_text())
    cohort = json.loads(ctx.inputs["cohort_summary"].read_text())
    gate = json.loads(ctx.inputs["verify"].read_text())
    signal = pd.read_csv(ctx.inputs["explore"] / "feature_signal.csv")
    calib = pd.read_csv(ctx.inputs["calibration"])
    detection = pd.read_csv(ctx.inputs["detection"])
    life_table = pd.read_csv(ctx.inputs["life"])
    preds = pd.read_parquet(ctx.inputs["predictions"])
    ref = metrics["reference"]
    labels = ctx.params.get("labels", {})
    meta_ref = json.loads(ctx.inputs[f"meta_{ref}"].read_text())
    figures(out, metrics, calib, detection, preds, meta_ref, ref, labels)

    disc = pd.DataFrame(metrics["discrimination"])
    gains = pd.DataFrame(metrics["reference_gain"])
    results = _results(metrics, cohort, gate, preds, ref, labels)
    (out / "results.md").write_text("\n".join(results) + "\n")

    lines = [
        "# Can SMART data predict when a hard drive will fail?",
        "",
        "The run itself (scale, cohort, test set, gate) and the headline numbers are in "
        "[results.md](results.md). This file explains them and holds the detailed tables.",
        "",
        "## Answer",
        "",
    ]
    lines += _answer(disc, gains, metrics, ref, labels, ctx.params["timing_tolerance"])
    lines += _discrimination(metrics, preds, labels)
    lines += _ablations(metrics, ref, labels)
    lines += _slices(metrics, ref, labels)
    lines += _concordance(metrics, labels)
    lines += _life(metrics, life_table, ref, labels)
    lines += _alerting(metrics, ref, labels)
    lines += _calibration(metrics, ref, labels)
    lines += _retirement(metrics, ref, labels)
    lines += ["", "## Which SMART attributes matter", "",
              "Single-attribute ROC-AUC on train snapshots (fails within "
              f"{meta_ref['binary_horizon']} days), computed only on the drive-days where "
              "the attribute is reported; \"filled\" is that share. 0.5 = no signal. Below "
              "0.5 means lower values go with failure (normalized values fall as a drive "
              "degrades).", ""]
    lines += table(["feature", "ROC-AUC", "filled"],
                   [[r["feature"], _fmt(r["auc"]), _pct(r["fill_rate"], 0)]
                    for _, r in signal.head(15).iterrows()])
    lines += ["", "![importance](importance.png)", "",
              "Also see `build/explore/km_by_counters.png` and `build/explore/models.csv`.", ""]
    (out / "analysis.md").write_text("\n".join(lines) + "\n")
    return {"results_lines": len(results), "analysis_lines": len(lines)}


def _pivot(rows, models, cell, labels, horizons):
    """One row per model, one column per horizon; models without any row are left out."""
    by = {(r["model"], r["horizon"]): r for r in rows}
    body = []
    for m in models:
        if any((m, H) in by for H in horizons):
            body.append([_label(m, labels)]
                        + [cell(by[(m, H)]) if (m, H) in by else "-" for H in horizons])
    return body


def _results(metrics, cohort, gate, preds, ref, labels) -> list[str]:
    """The run and its headline numbers, without discussion (that is analysis.md)."""
    scale, test = cohort["scale"], metrics["test"]
    split = cohort.get("by_split_stratum", {})
    per_split = ", ".join(
        f"{s} {sum(n for k, n in split.items() if k.startswith(s + '/'))}"
        for s in ("train", "val", "test") if any(k.startswith(s + "/") for k in split))
    dates = pd.to_datetime(preds["date"])
    span = lambda sp: (f"{dates[preds['split'] == sp].min().date()} to "  # noqa: E731
                       f"{dates[preds['split'] == sp].max().date()}"
                       if (preds["split"] == sp).any() else "n/a")
    ran = [c for c in gate["checks"] if c["status"] in ("pass", "fail", "error")]
    failed = [c for c in ran if c["status"] != "pass"]
    trained = [m for m in metrics.get("models", {}) if m != ref]
    hz = sorted({r["horizon"] for r in metrics["discrimination"]})
    head = [f"{H} d" for H in hz]
    H = _binary_horizon(metrics)

    lines = [
        "# Results",
        "",
        "Numbers only. What they mean, and the detailed tables behind them, are in "
        "[analysis.md](analysis.md).",
        "",
        "## Run",
        "",
    ]
    lines += table(["", ""], [
        ["scale", f"{scale['scale']} (failing drives sampled at "
                  f"{_pct(scale['failing_fraction'], 0)}, healthy at "
                  f"{_pct(scale['healthy_fraction'], 1)})"],
        ["cohort", f"{cohort['cohort_drives']} drives ({per_split})"],
        ["validation snapshots", span("val")],
        ["test snapshots", span("test")],
        ["test set", f"{test['drives']} drives, {test['failing_drives']} fail "
                     f"({test.get('silent_failing_drives', 'n/a')} silent), "
                     f"{test['snapshots']} snapshots"],
        ["reference model", _label(ref, labels)],
        ["compared with", f"{len(trained)} models and baselines (rows of the tables below)"],
        ["verification gate", f"{len(ran) - len(failed)}/{len(ran)} checks passed "
                              f"(data-verify {gate['version']}; {gate['counts']['skip']} "
                              "skipped: their roles are not declared)"
                              + "".join(f"; {c['id']} "
                                        + ("warned" if c["severity"] == "warn" else "failed")
                                        for c in failed)],
        ["intervals", f"95% drive-level bootstrap, {metrics['bootstrap_rounds']} rounds"],
    ])

    core = [r for r in metrics["discrimination"] if r["model"] in CORE]
    lines += ["", "## Ranking (ROC-AUC)", "",
              "> How well the score separates drives that fail within the horizon from those "
              "that don't. 0.5 = random, 1 = perfect.", ""]
    lines += table(["model"] + head,
                   _pivot(core, CORE, lambda r: est(r["auc"], r["auc_ci"]), labels, hz))

    base = {r["horizon"]: r["base_rate"] for r in core}
    lines += ["", "## Precision-recall (PR-AUC)", "",
              "> Failures are rare, so compare each value with the base rate (the real share "
              "of drive-days that fail within the horizon), which is what a random ranking "
              "scores.", ""]
    lines += table(["model"] + head,
                   [["base rate"] + [_fmt(base.get(h), 5) for h in hz]]
                   + _pivot(core, CORE, lambda r: est(r["ap"], r["ap_ci"], 4), labels, hz))

    others = [m for m in CORE + ABLATIONS if m != ref]
    gain_rows = [{**g, "model": g["other"]} for g in metrics["reference_gain"]]
    lines += ["", "## Reference gain over each model (ROC-AUC)", "",
              f"> The reference ({_label(ref, labels)}) minus the model in the row, paired "
              "on the same "
              "bootstrap rounds. An interval above zero means the reference ranks better; "
              "one that covers zero means no clear difference.", ""]
    lines += table(["model"] + head,
                   _pivot(gain_rows, others,
                          lambda g: est(g["auc_gain"], g["auc_gain_ci"], sign=True), labels, hz))

    main = _main_alert(metrics, ref)
    if main:
        rows = [a for a in metrics["alerting"] if a["budget"] == main["budget"]
                and a["model"] in CORE]
        rows.sort(key=lambda a: _rank(a["model"]))
        lines += ["", f"## Alerts at a {_pct(main['budget'], 1)} false-alarm budget", "",
                  f"> The threshold is set on validation drives so that {_pct(main['budget'], 1)} "
                  "of healthy drive-days alert. On test, false alarms above the budget mean "
                  f"drift. Precision = share of alerted drive-days that fail within "
                  f"{main['horizon']} days.", ""]
        lines += table(
            ["model", "false alarms (test)", "precision",
             f"failing drives alerted in their last {main['horizon']} d",
             f"alerted >= {main['early_days']} d before failure"],
            [[_label(a["model"], labels),
              est(a["false_alarm_rate_test"], a.get("false_alarm_rate_test_ci"), 2, pct=True),
              est(a["precision_test"], a.get("precision_test_ci"), 2, pct=True),
              f"{a['failing_drives_alerted']}/{a['failing_drives']}",
              f"{a.get('failing_drives_alerted_early', 'n/a')}/{a['failing_drives']}"]
             for a in rows])

    life = next((r for r in metrics["life"] if r["model"] == ref), None)
    if life:
        qc = life["quantile_calibration"]
        lines += ["", "## Remaining life", "",
                  "> For each snapshot the model names the day by which the failure "
                  "probability reaches 10%, 50% and 90%. If the timing is right, the share "
                  "that failed by that day matches the target. Below target = too "
                  "pessimistic, above = too optimistic.", ""]
        lines += table(["predicted day", "target", "failed by then", "snapshots"],
                       [[{"0.1": "10% day", "0.5": "median", "0.9": "90% day"}[q],
                         _pct(qc[q]["target"], 0),
                         _pct(qc[q]["share_failed_by_predicted_day"]), qc[q]["snapshots"]]
                        for q in ("0.1", "0.5", "0.9") if q in qc])
        lines += ["", f"Failing drives' snapshots with a median within a year: "
                  f"{_pct(life['share_median_within_horizon'])}. Healthy snapshots with a "
                  f"median beyond a year: {_pct(life['healthy_share_median_beyond_horizon'])}."]

    drift = next((r for r in metrics.get("drift", []) if r["model"] == ref), None)
    if drift:
        lo, hi = drift["val_band"]
        lines += ["", f"## Calibration over time ({H}-day risk)", "",
                  "> Ratio = mean predicted / observed risk. 1 = right, above 1 = the model "
                  f"over-predicts. Validation years span {_fmt(lo, 2)} to {_fmt(hi, 2)}; a "
                  "test year outside that band is drift.", ""]
        lines += table(["test year", "ratio", "outside validation band"],
                       [[t["year"], est(t.get("ratio"), t.get("ratio_ci"), 2),
                         "yes" if t["outside_band"] else "no"] for t in drift["test_years"]])

    return lines


def _discrimination(metrics, preds, labels) -> list[str]:
    rows = _sorted([r for r in metrics["discrimination"] if r["model"] in CORE], "horizon")
    pos_drives = sorted({r["positive_drives"] for r in rows})
    if len(pos_drives) == 1:
        drives_note = (f"All {pos_drives[0]} failing test drives are positive at every "
                       "horizon (each has snapshots close to its failure day), so the last "
                       "column counts positive snapshots instead.")
    else:
        drives_note = (f"Failing test drives with a positive snapshot: {pos_drives[0]} to "
                       f"{pos_drives[-1]}, depending on the horizon.") if pos_drives else ""
    lines = ["", "## Discrimination by horizon", "",
             "ROC-AUC and PR-AUC per drive-day snapshot, on test snapshots whose status at "
             "the horizon is known, weighted to real prevalence. Brackets: 95% drive-level "
             f"bootstrap ({metrics['bootstrap_rounds']} rounds). Base rate = real share of "
             f"drive-days that fail within the horizon. {drives_note}", ""]
    lines += table(["horizon", "model", "ROC-AUC", "PR-AUC", "Brier", "base rate",
                    "positive snapshots"],
                   [[f"{r['horizon']} d", _label(r["model"], labels), est(r["auc"], r["auc_ci"]),
                     est(r["ap"], r["ap_ci"], 4), _fmt(r["brier"], 5),
                     _pct(r["base_rate"], 3), r["positive_snapshots"]] for r in rows])
    for H, why in metrics.get("skipped_horizons", {}).items():
        lines.append(f"\n{H}-day horizon not estimable on this test set: {why}.")
    if rows:
        lines += ["", _follow_up_note(preds, rows)]
    lines += ["", "**Robustness.** The same ranking with inverse-probability-of-censoring "
              "weights (IPCW: snapshots whose status is unknown are represented by weighting up "
              "comparable known ones, instead of being dropped), and a drive-level ROC-AUC on "
              "one random snapshot per drive, weighted per drive (so drives with many "
              "snapshots do not dominate). Brier skill = 1 - Brier / Brier of always predicting "
              "the base rate; above 0 beats that constant.", ""]
    lines += table(["horizon", "model", "ROC-AUC, IPCW (per drive-day)",
                    "PR-AUC, IPCW (per drive-day)", "ROC-AUC (per drive)", "Brier skill"],
                   [[f"{r['horizon']} d", _label(r["model"], labels),
                     est(r.get("auc_ipcw"), r.get("auc_ipcw_ci")),
                     est(r.get("ap_ipcw"), r.get("ap_ipcw_ci"), 4),
                     est(r.get("auc_drive"), r.get("auc_drive_ci")),
                     _fmt(r.get("brier_skill"), 3)] for r in rows])
    lines += ["", "![AUC by horizon](auc_by_horizon.png)"]
    return lines


def _ablations(metrics, ref, labels) -> list[str]:
    disc = {(r["horizon"], r["model"]): r for r in metrics["discrimination"]}
    gain = {(g["horizon"], g["other"]): g for g in metrics["reference_gain"]}
    present = [m for m in ABLATIONS if m in metrics.get("models", {})]
    if not present:
        return []
    lines = ["", "## Ablations and sensitivity", "",
             f"Each variant against the reference ({_label(ref, labels)}). Gain = reference minus "
             "variant, paired on the same bootstrap rounds; \"not better\" = share of rounds "
             "where the reference's ROC-AUC is not higher.", ""]
    lines += [f"- **{_label(m, labels)}**: {WHY[m]}" for m in present]
    lines.append("")
    rows = []
    for H in sorted({h for h, _ in disc}):
        r = disc.get((H, ref))
        if r:
            rows.append([f"{H} d", f"{_label(ref, labels)} (reference)", est(r["auc"], r["auc_ci"]),
                         "", "", ""])
        for m in present:
            r, g = disc.get((H, m)), gain.get((H, m))
            if not r:
                continue
            rows.append([f"{H} d", _label(m, labels), est(r["auc"], r["auc_ci"]),
                         est(g["auc_gain"], g["auc_gain_ci"], sign=True) if g else "n/a",
                         est(g["ap_gain"], g["ap_gain_ci"], 4, sign=True) if g else "n/a",
                         _pct(g["share_of_rounds_reference_not_better"], 0) if g else "n/a"])
    lines += table(["horizon", "model", "ROC-AUC", "reference gain, ROC-AUC",
                    "reference gain, PR-AUC", "not better"], rows)
    return lines


def _slices(metrics, ref, labels) -> list[str]:
    rows = metrics.get("slices", [])
    if not rows:
        return []
    H = _binary_horizon(metrics)
    shown = [ref, "hazard_nosmart", "rule_counters"]
    overall = {(r["horizon"], r["model"]): r for r in metrics["discrimination"]}
    lines = ["", "## Where the signal comes from", "",
             "The ranking metrics on parts of the test set, per drive-day snapshot. "
             "Positive-side slices (lead time, silent or not) keep every known-healthy "
             "snapshot and restrict the failing ones, so their base rate is lower; population "
             "slices (vendor, capacity, entry date) restrict both. \"Silent\" failures are "
             "drives that fail with none of the critical counters (5, 187, 197, 198) above "
             f"zero in any test snapshot. At {H} days:", ""]
    body = []
    for name in ["all test snapshots"] + list(dict.fromkeys(r["slice"] for r in rows
                                                             if r["horizon"] == H)):
        for m in shown:
            r = overall.get((H, m)) if name == "all test snapshots" else next(
                (x for x in rows if x["slice"] == name and x["horizon"] == H
                 and x["model"] == m), None)
            if r:
                body.append([name, _label(m, labels), est(r["auc"], r["auc_ci"]),
                             est(r["ap"], r["ap_ci"], 4), _pct(r["base_rate"], 3),
                             r["positive_drives"]])
    lines += table(["slice", "model", "ROC-AUC", "PR-AUC", "base rate", "positive drives"],
                   body)
    keep = [s for s in dict.fromkeys(r["slice"] for r in rows)
            if s.startswith("silent") or s.startswith("positives >=")]
    body = []
    for s in keep:
        for r in sorted((x for x in rows if x["slice"] == s and x["model"] == ref),
                        key=lambda x: x["horizon"]):
            body.append([s, f"{r['horizon']} d", est(r["auc"], r["auc_ci"]),
                         est(r["ap"], r["ap_ci"], 4), _pct(r["base_rate"], 3),
                         r["positive_drives"]])
    if body:
        lines += ["", f"The same two slices for {_label(ref, labels)} across horizons:", ""]
        lines += table(["slice", "horizon", "ROC-AUC", "PR-AUC", "base rate",
                        "positive drives"], body)
    return lines


def _concordance(metrics, labels) -> list[str]:
    rows = sorted(metrics["concordance"], key=lambda r: _rank(r["model"]))
    lines = ["", "## Ranking over the whole future (concordance)", "",
             "Concordance between each model's risk score and the actual time to failure; "
             "0.5 = random. Harrell's C counts the comparable pairs (the earlier time is a "
             "failure) where the riskier snapshot fails first. Uno's C weights each pair by "
             "the inverse probability of staying uncensored, so it does not depend on how "
             "much follow-up the test period allows, and is truncated at "
             f"{metrics.get('concordance_tau_days', 'n/a')} days. Computed on "
             f"{metrics['concordance_rows']} test snapshots of "
             f"{metrics.get('concordance_drives', 'n/a')} drives (drives sampled whole up to "
             "a row cap). Score: -rmst_days = minus the expected days survived within a "
             "year; p30 = predicted 30-day risk, so hazard models can be compared with the "
             "classifier on the same kind of score. Intervals only on each model's main "
             "score.", ""]
    lines += table(["model", "score", "Harrell's C", "Uno's C"],
                   [[_label(r["model"], labels), r["score"], est(r["harrell"], r.get("harrell_ci")),
                     est(r["uno"], r.get("uno_ci"))] for r in rows])
    return lines


def _life(metrics, life_table, ref, labels) -> list[str]:
    life = sorted(metrics["life"], key=lambda r: _rank(r["model"]))
    lines = ["", "## When will it fail? Remaining-life estimates", "",
             "From each snapshot the survival model gives a curve: the day by which the "
             "failure probability reaches 10%, 50% (the median remaining life) and 90%. "
             "Beyond 365 days the model has no bins, so the answer is \"more than a year\"."]
    r_ref = next((r for r in life if r["model"] == ref), None)
    if r_ref and r_ref.get("share_finite_median_all") is not None:
        lines[-1] += (f" For {_pct(r_ref['share_finite_median_all'])} of all test snapshots "
                      f"the predicted median of {_label(ref, labels)} is within a year; "
                      "otherwise the answer is \"more than a year\".")
    lines += ["", "**Are the predicted days right?** Among snapshots whose predicted day falls "
              "within a year, the share that actually failed by that day should be close to "
              "the target:", ""]
    body = []
    for r in life:
        cells = [_label(r["model"], labels)]
        for q in ("0.1", "0.5", "0.9"):
            c = r["quantile_calibration"][q]
            cells.append(f"{_pct(c['share_failed_by_predicted_day'])} (target "
                         f"{_pct(c['target'], 0)}, {c['snapshots']} snapshots)")
        body.append(cells)
    lines += table(["model", "failed by predicted 10% day", "failed by predicted median",
                    "failed by predicted 90% day"], body)
    lines += ["", "**How early is a failure visible?** Snapshots of drives that do fail within "
              "a year, by how far away the failure actually was. A median within a year means "
              "the model already expects the drive to die within a year. The absolute error "
              "is over the failing snapshots whose median is within a year (count in "
              "brackets):", ""]
    lines += table(["model", "failing snapshots: median within a year",
                    "abs. error of median (days)", "all test snapshots: median within a year",
                    "healthy snapshots: median beyond a year"],
                   [[_label(r["model"], labels), _pct(r["share_median_within_horizon"]),
                     f"{_fmt(r['median_abs_error_days'], 0)} "
                     f"({r.get('median_abs_error_snapshots', 'n/a')} snapshots)",
                     _pct(r.get("share_finite_median_all")),
                     _pct(r["healthy_share_median_beyond_horizon"])] for r in life])
    ref_life = life_table[life_table["model"] == ref]
    if not ref_life.empty:
        lines += ["", f"By actual time to failure ({_label(ref, labels)}). Shares are of the "
                  "failing drives' snapshots in each bucket:", ""]
        lines += table(["actual days to failure", "snapshots", "median predicted within a year",
                        "median of predicted median (days)"],
                       [[r["actual_days_to_failure"], r["snapshots"],
                         _pct(r["share_median_within_horizon"]),
                         _days(r["median_of_predicted_median"])]
                        for _, r in ref_life.iterrows()])
    lines += ["", "![remaining life](remaining_life.png)"]
    return lines


def _alerting(metrics, ref, labels) -> list[str]:
    main = _main_alert(metrics, ref)
    if not main:
        return []
    shown = CORE + ["hazard_smart_recent"]
    rows = _sorted([a for a in metrics["alerting"] if a["model"] in shown], "budget")
    budgets = sorted({a["budget"] for a in rows})
    others = [_pct(b, 1) for b in budgets if b != main["budget"]]
    lines = ["", "## Early warning", "",
             "Each alert threshold is set on validation drives so that a given share of "
             f"healthy drive-days raises an alert (the budget). At the main budget of "
             f"{_pct(main['budget'], 1)}, {_pct(main['false_alarm_rate_val'], 2)} of "
             f"validation drive-days alert for {_label(main['model'], labels)}"
             + (f"; budgets of {', '.join(others)} are shown too" if others else "")
             + ". Test results: false alarms and precision are per drive-day; precision "
             f"counts alerts whose outcome at {main['horizon']} days is known, and the alerts "
             "that cannot be judged yet (panel end) are shown separately and, in the next "
             "column, counted as false. Failing drives alerted = drives failing in the test "
             f"period that get at least one alert in their last {main['horizon']} days.", ""]
    lines += table(
        ["budget", "model", "false alarms, test (share of healthy drive-days)",
         "precision (per alerted drive-day)", "alerts with unknown outcome",
         "precision, unknown as false", "failing drives alerted (drives)",
         f"alerted >= {main['early_days']} days before failure (drives)"],
        [[_pct(a["budget"], 1), _label(a["model"], labels),
          est(a["false_alarm_rate_test"], a.get("false_alarm_rate_test_ci"), 2, pct=True),
          est(a["precision_test"], a.get("precision_test_ci"), 2, pct=True),
          _pct(a.get("unknown_alert_share"), 1),
          est(a.get("precision_unknown_as_false"), a.get("precision_unknown_as_false_ci"), 2,
              pct=True),
          f"{a['failing_drives_alerted']}/{a['failing_drives']}, "
          + est(a.get("share_failing_drives_alerted"),
                a.get("share_failing_drives_alerted_ci"), 0, pct=True),
          f"{a.get('failing_drives_alerted_early', 'n/a')}/{a['failing_drives']}"]
         for a in rows])
    over = [a for a in rows if a["budget"] == main["budget"]
            and side(a.get("false_alarm_rate_test_ci"), a["budget"]) > 0]
    if over:
        lines += ["", "At the main budget the test false-alarm rate is above the budget, with "
                  "an interval that excludes it, for "
                  + ", ".join(_label(a["model"], labels) for a in over)
                  + ": healthy test drives score higher than the validation drives the "
                  "threshold was set on. This is the same shift over time that Calibration "
                  "over time shows (drift)."]
    else:
        lines += ["", "At the main budget no model's test false-alarm rate is above the budget "
                  "with an interval that excludes it, so the validation thresholds carry over "
                  "to the test years (see Calibration over time for the risk levels)."]
    lines += ["", "![detection](detection.png)"]
    return lines


def _calibration(metrics, ref, labels) -> list[str]:
    recent = f"{ref}_recent"
    shown = [m for m in (ref, recent) if m in metrics.get("models", {})]
    H = _binary_horizon(metrics)
    cal = [r for r in metrics.get("calibration_in_the_large", []) if r["horizon"] == H]
    drift = {r["model"]: r for r in metrics.get("drift", [])}
    lines = ["", "## Calibration", "",
             "Mean predicted failure probability vs the Kaplan-Meier observed share, by "
             "decile of predicted risk. Points on the diagonal mean that a predicted 5% "
             "really fails 5% of the time.", "", "![calibration](calibration.png)", "",
             "**Calibration over time** (mean predicted vs observed risk of failing within "
             f"{H} days; ratio = predicted / observed with a 95% drive bootstrap). Validation "
             "drives are from the training era, test from 2024 on. A gap that appears only in "
             "the test years is drift. \"Outside band\" = the test year's ratio is outside the "
             f"range of the validation-year ratios. Reference = {_label(ref, labels)}; "
             f"recalibrated = {_label(recent, labels)}.", ""]
    short = {ref: "reference", recent: "recalibrated"}
    header = ["split", "year", "snapshots", "observed"]
    for m in shown:
        header += [f"predicted ({short[m]})", f"ratio ({short[m]})",
                   f"outside band ({short[m]})"]
    body = []
    for split, year in sorted({(r["split"], r["year"]) for r in cal},
                              key=lambda k: (k[0] != "val", k[1])):
        by = {r["model"]: r for r in cal if r["split"] == split and r["year"] == year}
        if ref not in by:
            continue
        row = [split, year, by[ref]["snapshots"], _pct(by[ref]["observed_km"], 3)]
        for m in shown:
            r = by.get(m)
            if not r:
                row += ["n/a"] * 3
                continue
            flag = "-"
            if split == "test":
                t = next((t for t in drift.get(m, {}).get("test_years", [])
                          if t["year"] == year), None)
                flag = "n/a" if t is None else "yes" if t["outside_band"] else "no"
            row += [_pct(r["predicted"], 3), est(r.get("ratio"), r.get("ratio_ci"), 2), flag]
        body.append(row)
    lines += table(header, body)
    lines.append("")
    for m in shown:
        if m in drift:
            lines.append(_drift_sentence(drift[m], _label(m, labels)))
        else:
            lines.append(f"- {_label(m, labels)}: fewer than three validation years with an "
                         "observed failure, so there is no validation band to compare with.")
    return lines


def _retirement(metrics, ref, labels) -> list[str]:
    rows = sorted((r for r in metrics.get("retirement", []) if r["model"] == ref),
                  key=lambda r: (r["split"] != "val", r["year"]))
    if not rows:
        return []
    H = _binary_horizon(metrics)
    above = [r for r in rows if r["risk_ratio"] is not None and r["risk_ratio"] > 1]
    rated = [r for r in rows if r["risk_ratio"] is not None]
    lines = ["", "## Retirement", "",
             "Drives that never fail and have snapshots in a year, split into those that stop "
             "reporting before the end of the next year (left) and those still reporting "
             "(stayed). The survival estimates assume that leaving is unrelated to health; "
             "then both groups would carry about the same predicted risk. A ratio above 1 "
             "means the drives that leave already looked riskier beforehand: censoring is "
             "probably informative (drives are retired before they can fail), and the "
             "observed failure risk is underestimated. The alert threshold is the main-budget "
             f"threshold of {_label(ref, labels)}.", ""]
    lines += table(["split", "year", "drives left", "drives stayed",
                    f"mean predicted {H}-day risk, left", f"mean predicted {H}-day risk, stayed",
                    "ratio left/stayed", "above alert threshold, left",
                    "above alert threshold, stayed"],
                   [[r["split"], r["year"], r["drives_left"], r["drives_stayed"],
                     _pct(r["mean_p_left"], 3), _pct(r["mean_p_stayed"], 3),
                     _fmt(r["risk_ratio"], 2), _pct(r["share_above_threshold_left"], 2),
                     _pct(r["share_above_threshold_stayed"], 2)] for r in rows])
    if rated:
        lines += ["", f"The ratio is above 1 in {len(above)} of {len(rated)} split-years with "
                  "drives in both groups (no intervals: read it as a direction, not a test)."]
    return lines


def _timing_verdict(qc: dict, tolerance: float) -> str:
    """One sentence on whether predicted failure days are early, late or about right.

    Each quantile's miss (share failed by the predicted day minus its target) is scaled
    by the largest miss possible for that target; "about right" means the mean scaled miss
    is within `tolerance`.
    """
    off = []
    for c in qc.values():
        share, target = c["share_failed_by_predicted_day"], c["target"]
        if share is not None and c["snapshots"] >= 30:
            off.append((share - target) / max(target, 1 - target))
    if not off:
        return "Too few snapshots with a predicted day within a year to judge timing."
    mean = float(np.mean(off))
    if abs(mean) <= tolerance:
        return "When the model names a day within the next year, it is about right on average:"
    if mean < 0:
        return ("When the model names a day within the next year, it is too pessimistic "
                "(drives fail later than predicted):")
    return ("When the model names a day within the next year, it is too optimistic (drives "
            "fail earlier than predicted):")


def _gain_row(gains, other, horizon=None):
    if gains.empty:
        return None
    g = gains[gains["other"] == other]
    if horizon is not None:
        g = g[g["horizon"] == horizon]
    return g.sort_values("horizon").iloc[0] if not g.empty else None


def _answer(disc, gains, metrics, ref, labels, tolerance) -> list[str]:
    out = []
    H = _binary_horizon(metrics)
    nosmart = "hazard_nosmart"
    g = gains[gains["other"] == nosmart] if not gains.empty else gains
    if not g.empty:
        clear = g[g["auc_gain_ci"].map(lambda c: side(c) > 0)]
        out.append(
            "- **Do SMART metrics carry failure information?** "
            + ("Yes. " if len(clear) == len(g) else
               "Partly. " if len(clear) else "Not clearly at this scale. ")
            + f"Adding SMART to what is known without it (drive model, capacity, time in "
            f"service) improves ROC-AUC at {len(clear)} of {len(g)} horizons with a 95% "
            "interval that excludes zero:")
        for _, r in g.sort_values("horizon").iterrows():
            out.append(f"  - {r['horizon']} days: {r['auc_gain']:+.3f} {_ci(r['auc_gain_ci'])}")
    r = _gain_row(gains, "hazard_nocritical", H)
    if r is not None:
        nc = gains[gains["other"] == "hazard_nocritical"]
        n_clear = int(nc["auc_gain_ci"].map(lambda c: side(c) > 0).sum())
        out.append(
            "- **How much of that is the replacement policy?** Backblaze replaces drives "
            "when counters 5, 187, 188, 197 or 198 rise, so those counters partly define the "
            "failure label. The full model's ROC-AUC exceeds the model without them by "
            f"{r['auc_gain']:+.3f} {_ci(r['auc_gain_ci'])} at {H} days (an interval above "
            f"zero at {n_clear} of {len(nc)} horizons). The SMART gain above "
            "is therefore an upper bound on what SMART adds beyond the operator's "
            "replacement policy.")
    short = disc[(disc["model"] == ref)].sort_values("horizon")
    if not short.empty:
        first, last = short.iloc[0], short.iloc[-1]
        out.append(
            f"- **How far ahead?** Ranking is strongest close to failure (ROC-AUC "
            f"{first['auc']:.3f} for {first['horizon']} days) and weaker for the long term "
            f"({last['auc']:.3f} for {last['horizon']} days; long horizons are measured on "
            "earlier test snapshots, see Discrimination by horizon).")
        out.append(
            f"- **But failures are rare.** Even within {first['horizon']} days only "
            f"{_pct(first['base_rate'], 3)} of drive-days fail. The model's PR-AUC there is "
            f"{first['ap']:.4f} (a random ranking would score about the base rate), so at "
            "any useful recall many alerts are false (see Early warning).")
    slices = pd.DataFrame(metrics.get("slices", []))
    overall = disc[(disc["model"] == ref) & (disc["horizon"] == H)]
    if not slices.empty and not overall.empty:
        o = overall.iloc[0]
        ref_s = slices[(slices["model"] == ref) & (slices["horizon"] == H)]
        lead = ref_s[ref_s["slice"].str.startswith("positives >=")]
        if not lead.empty:
            s = lead.iloc[0]
            below = _ci_ok(s["ap_ci"]) and s["ap_ci"][1] < o["ap"]
            out.append(
                f"- **Is it more than the last days?** Counting as positives only snapshots "
                f"{s['slice'].removeprefix('positives ')}, the {H}-day PR-AUC is "
                f"{est(s['ap'], s['ap_ci'], 4)} against {o['ap']:.4f} overall (base rate "
                f"{_pct(s['base_rate'], 3)} vs {_pct(o['base_rate'], 3)}); ROC-AUC "
                f"{est(s['auc'], s['auc_ci'])}. "
                + ("Much of the precision comes from the last days before failure."
                   if below else "The interval does not exclude the overall value."))
        silent = ref_s[ref_s["slice"].str.startswith("silent")]
        if not silent.empty and "silent_failing_drives" in metrics["test"]:
            s = silent.iloc[0]
            verdict = ("still above chance" if side(s["auc_ci"], 0.5) > 0 else
                       "not distinguishable from chance" if side(s["auc_ci"], 0.5) == 0
                       else "below chance")
            out.append(
                f"- **Silent failures** (no critical counter above zero in any test "
                f"snapshot): {metrics['test']['silent_failing_drives']} of the "
                f"{metrics['test']['failing_drives']} failing test drives. On them the "
                f"{H}-day ROC-AUC of {_label(ref, labels)} is "
                f"{est(s['auc'], s['auc_ci'])} against {est(o['auc'], o['auc_ci'])} overall: "
                f"{verdict}.")
    life = next((r for r in metrics["life"] if r["model"] == ref), None)
    if life:
        qc = life["quantile_calibration"]
        out.append(
            f"- **When will it probably fail?** {_timing_verdict(qc, tolerance)} "
            f"{_pct(qc['0.1']['share_failed_by_predicted_day'])} of drives failed by their "
            f"predicted 10% day, {_pct(qc['0.5']['share_failed_by_predicted_day'])} by the "
            f"predicted median and {_pct(qc['0.9']['share_failed_by_predicted_day'])} by the "
            "predicted 90% day (targets 10/50/90%). For drives that do fail within a year it "
            f"names a median within a year only {_pct(life['share_median_within_horizon'])} of "
            "the time: most failures are not visible in SMART long in advance. For healthy "
            f"drives it says \"more than a year\" "
            f"{_pct(life['healthy_share_median_beyond_horizon'])} of the time.")
    b = _gain_row(gains, "binary_30d", H)
    if b is not None:
        s = side(b["auc_gain_ci"])
        out.append(
            f"- **One survival model or a dedicated {H}-day classifier?** At {H} days the "
            f"survival model's ROC-AUC minus the classifier's is {b['auc_gain']:+.3f} "
            f"{_ci(b['auc_gain_ci'])} (paired bootstrap), PR-AUC {b['ap_gain']:+.4f} "
            f"{_ci(b['ap_gain_ci'], 4)}; the survival model is not better in "
            f"{_pct(b['share_of_rounds_reference_not_better'], 0)} of rounds. "
            + ("The survival model ranks better." if s > 0 else
               "The classifier ranks better." if s < 0 else
               "Neither ranks clearly better, and the survival model also covers the other "
               "horizons."))
    rule = _gain_row(gains, "rule_counters")
    if rule is not None:
        out.append(
            f"- **Against the classic rule** (log-sum of the reallocated, reported-uncorrectable, "
            f"pending and offline-uncorrectable sector counters 5, 187, 197, 198), the model "
            f"gains {rule['auc_gain']:+.3f} ROC-AUC {_ci(rule['auc_gain_ci'])} at "
            f"{rule['horizon']} days.")
    return out

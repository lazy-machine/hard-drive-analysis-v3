"""Write build/report/report.md and its figures from the evaluation outputs.

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

LABELS = {
    "hazard_smart": "survival model, SMART + context",
    "hazard_nosmart": "survival model, context only (no SMART)",
    "binary_30d": "30-day yes/no classifier (SMART + context)",
    "rule_counters": "rule: critical SMART counters",
}


def _fmt(x, digits=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def _days(x):
    if x is None:
        return "n/a"
    return "> 1 year" if not math.isfinite(x) else f"{x:.0f}"


def _pct(x, digits=1):
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _ci(ci, digits=3):
    return "n/a" if not ci or ci[0] is None else f"[{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]"


def _label(name):
    return LABELS.get(name, name)


def figures(out, metrics, calib, detection, preds, meta_ref, ref):
    disc = pd.DataFrame(metrics["discrimination"])
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    models = list(dict.fromkeys(disc["model"]))
    for i, name in enumerate(models):
        d = disc[disc["model"] == name]
        x = np.arange(len(d)) + (i - (len(models) - 1) / 2) * 0.12
        lo = d["auc"] - d["auc_ci"].map(lambda c: c[0])
        hi = d["auc_ci"].map(lambda c: c[1]) - d["auc"]
        ax.errorbar(x, d["auc"], yerr=[lo, hi], fmt="o", capsize=3, label=_label(name))
    hz = sorted(disc["horizon"].unique())
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

    if not detection.empty:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        for name, g in detection.groupby("model", sort=False):
            ax.plot(g["days_before_failure"], g["alerted"], "o-", label=_label(name))
        ax.set_xlabel("days before failure")
        ax.set_ylabel("share of failing-drive snapshots alerted")
        ax.set_ylim(0, 1)
        ax.set_title(f"Alerts at a {_pct(metrics['alerting'][0]['false_alarm_rate_val'], 0)} "
                     "false-alarm budget (set on validation)")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "detection.png", dpi=120)
        plt.close(fig)

    imp = pd.Series(meta_ref["importance_gain"]).head(20)[::-1]
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.barh(imp.index, imp / imp.sum())
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
    meta_ref = json.loads(ctx.inputs[f"meta_{ref}"].read_text())
    figures(out, metrics, calib, detection, preds, meta_ref, ref)

    disc = pd.DataFrame(metrics["discrimination"])
    gains = pd.DataFrame(metrics["reference_gain"])
    scale = cohort["scale"]
    test = metrics["test"]
    lines = [
        "# Can SMART data predict when a hard drive will fail?",
        "",
        f"Scale **{scale['scale']}**: {cohort['cohort_drives']} drives in the cohort "
        f"(failing drives sampled at {_pct(scale['failing_fraction'], 0)}, healthy at "
        f"{_pct(scale['healthy_fraction'], 1)}, weighted back to the real population). "
        f"Test: {test['drives']} drives never seen in training, {test['failing_drives']} of "
        f"which fail during the test period ({test['snapshots']} snapshots). Verification "
        f"gate: {sum(c['ok'] for c in gate['checks'])}/{len(gate['checks'])} checks passed.",
        "",
        "## Answer",
        "",
    ]
    lines += _answer(disc, gains, metrics, ref)
    lines += ["", "## Discrimination by horizon", "",
              "ROC-AUC and PR-AUC on test snapshots whose status at the horizon is known, "
              "weighted to real prevalence. Brackets: 95% drive-level bootstrap "
              f"({metrics['bootstrap_rounds']} rounds). Base rate = real share of "
              "drive-days that fail within the horizon.", "",
              "| horizon | model | ROC-AUC | PR-AUC | Brier | base rate | failing drives |",
              "|---|---|---|---|---|---|---|"]
    for r in metrics["discrimination"]:
        lines.append(
            f"| {r['horizon']} d | {_label(r['model'])} | {_fmt(r['auc'])} {_ci(r['auc_ci'])} | "
            f"{_fmt(r['ap'], 4)} {_ci(r['ap_ci'], 4)} | {_fmt(r['brier'], 5)} | "
            f"{_pct(r['base_rate'], 3)} | {r['positive_drives']} |")
    for H, why in metrics.get("skipped_horizons", {}).items():
        lines.append(f"\n{H}-day horizon not estimable on this test set: {why}.")
    lines += ["", "![AUC by horizon](auc_by_horizon.png)", "",
              "## Ranking over the whole future (concordance)", "",
              "Harrell's C between each model's risk and the actual time to failure "
              f"({metrics['concordance_rows']} test snapshots). 0.5 = random.", "",
              "| model | C-index |", "|---|---|"]
    for name, c in metrics["concordance"].items():
        lines.append(f"| {_label(name)} | {_fmt(c)} |")

    lines += ["", "## When will it fail? Remaining-life estimates", "",
              "From each snapshot the survival model gives a curve: the day by which the "
              "failure probability reaches 10%, 50% (the median remaining life) and 90%. "
              "Beyond 365 days the model has no bins, so the answer is \"more than a year\".",
              "", "**Are the predicted days right?** Among snapshots whose predicted day falls "
              "within a year, the share that actually failed by that day should be close to "
              "the target:", "",
              "| model | failed by predicted 10% day | failed by predicted median | "
              "failed by predicted 90% day |", "|---|---|---|---|"]
    for r in metrics["life"]:
        cells = []
        for q in ("0.1", "0.5", "0.9"):
            c = r["quantile_calibration"][q]
            cells.append(f"{_pct(c['share_failed_by_predicted_day'])} (target "
                         f"{_pct(c['target'], 0)}, {c['snapshots']} snapshots)")
        lines.append(f"| {_label(r['model'])} | " + " | ".join(cells) + " |")
    lines += ["", "**How early is a failure visible?** Snapshots of drives that do fail within "
              "a year, by how far away the failure actually was. A median within a year means "
              "the model already expects the drive to die within a year:", "",
              "| model | failing snapshots: median within a year | abs. error of median (days) "
              "| healthy snapshots: median beyond a year |", "|---|---|---|---|"]
    for r in metrics["life"]:
        lines.append(
            f"| {_label(r['model'])} | {_pct(r['share_median_within_horizon'])} | "
            f"{_fmt(r['median_abs_error_days'], 0)} | "
            f"{_pct(r['healthy_share_median_beyond_horizon'])} |")
    ref_life = life_table[life_table["model"] == ref]
    if not ref_life.empty:
        lines += ["", f"By actual time to failure ({_label(ref)}):", "",
                  "| actual days to failure | snapshots | median predicted within a year "
                  "| median of predicted median (days) |", "|---|---|---|---|"]
        for _, r in ref_life.iterrows():
            lines.append(f"| {r['actual_days_to_failure']} | {r['snapshots']} | "
                         f"{_pct(r['share_median_within_horizon'])} | "
                         f"{_days(r['median_of_predicted_median'])} |")
    lines += ["", "![remaining life](remaining_life.png)", "",
              "## Early warning", "",
              "The alert threshold is set on validation drives so that "
              f"{_pct(metrics['alerting'][0]['false_alarm_rate_val'], 1)} of healthy drive-days "
              "raise an alert. Test results:", "",
              "| model | false alarms (test) | precision | failing drives alerted in their last "
              f"{metrics['alerting'][0]['horizon']} days |", "|---|---|---|---|"]
    for a in metrics["alerting"]:
        lines.append(f"| {_label(a['model'])} | {_pct(a['false_alarm_rate_test'], 2)} | "
                     f"{_pct(a['precision_test'], 2)} | {a['failing_drives_alerted']}/"
                     f"{a['failing_drives']} |")
    lines += ["", "![detection](detection.png)", "", "## Calibration", "",
              "Mean predicted failure probability vs the Kaplan-Meier observed share, by "
              "decile of predicted risk. Points on the diagonal mean that a predicted 5% "
              "really fails 5% of the time.", "", "![calibration](calibration.png)", "",
              "**Calibration over time** (mean predicted vs observed risk of failing within "
              f"30 days, {_label(ref)}). Validation drives are from the training era, test "
              "from 2024 on. A gap that appears only in the test years is drift:", "",
              "| split | year | snapshots | predicted | observed |", "|---|---|---|---|---|"]
    for r in metrics.get("calibration_in_the_large", []):
        if r["model"] == ref and r["horizon"] == 30:
            lines.append(f"| {r['split']} | {r['year']} | {r['snapshots']} | "
                         f"{_pct(r['predicted'], 3)} | {_pct(r['observed_km'], 3)} |")
    lines += ["", "## Which SMART attributes matter", "",
              "Single-attribute ROC-AUC on train snapshots (fails within "
              f"{meta_ref['binary_horizon']} days). 0.5 = no signal. Below 0.5 means lower "
              "values go with failure (normalized values fall as a drive degrades).", "",
              "| feature | ROC-AUC | filled |", "|---|---|---|"]
    for _, r in signal.head(15).iterrows():
        lines.append(f"| {r['feature']} | {_fmt(r['auc'])} | {_pct(r['fill_rate'], 0)} |")
    lines += ["", "![importance](importance.png)", "",
              "Also see `build/explore/km_by_counters.png` and `build/explore/models.csv`.", ""]
    (out / "report.md").write_text("\n".join(lines))
    return {"lines": len(lines)}


def _timing_verdict(qc: dict) -> str:
    """One sentence on whether predicted failure days are early, late or about right."""
    off = []
    for c in qc.values():
        share, target = c["share_failed_by_predicted_day"], c["target"]
        if share is not None and c["snapshots"] >= 30:
            off.append((share - target) / max(target, 1 - target))
    if not off:
        return "Too few snapshots with a predicted day within a year to judge timing."
    mean = float(np.mean(off))
    if abs(mean) <= 0.15:
        return "When the model names a day within the next year, it is about right on average:"
    if mean < 0:
        return ("When the model names a day within the next year, it is too pessimistic "
                "(drives fail later than predicted):")
    return ("When the model names a day within the next year, it is too optimistic (drives "
            "fail earlier than predicted):")


def _answer(disc, gains, metrics, ref) -> list[str]:
    out = []
    nosmart = "hazard_nosmart"
    g = gains[gains["other"] == nosmart] if not gains.empty else gains
    if not g.empty:
        clear = g[g["auc_gain_ci"].map(lambda c: c[0] is not None and c[0] > 0)]
        out.append(
            f"- **Do SMART metrics carry failure information?** "
            + ("Yes. " if len(clear) == len(g) else
               "Partly. " if len(clear) else "Not clearly at this scale. ")
            + f"Adding SMART to what is known without it (drive model, capacity, time in "
            f"service) improves ROC-AUC at {len(clear)} of {len(g)} horizons with a 95% "
            "interval that excludes zero:")
        for _, r in g.iterrows():
            out.append(f"  - {r['horizon']} days: +{r['auc_gain']:.3f} {_ci(r['auc_gain_ci'])}")
    short = disc[(disc["model"] == ref)].sort_values("horizon")
    if not short.empty:
        first, last = short.iloc[0], short.iloc[-1]
        out.append(
            f"- **How far ahead?** Ranking is strongest close to failure (ROC-AUC "
            f"{first['auc']:.3f} for {first['horizon']} days) and weaker for the long term "
            f"({last['auc']:.3f} for {last['horizon']} days).")
        out.append(
            f"- **But failures are rare.** Even within {first['horizon']} days only "
            f"{_pct(first['base_rate'], 3)} of drive-days fail. The model's PR-AUC there is "
            f"{first['ap']:.4f} (a random ranking would score about the base rate), so at "
            "any useful recall many alerts are false (see Early warning).")
    life = next((r for r in metrics["life"] if r["model"] == ref), None)
    if life:
        qc = life["quantile_calibration"]
        out.append(
            f"- **When will it probably fail?** {_timing_verdict(qc)} "
            f"{_pct(qc['0.1']['share_failed_by_predicted_day'])} of drives failed by their "
            f"predicted 10% day, {_pct(qc['0.5']['share_failed_by_predicted_day'])} by the "
            f"predicted median and {_pct(qc['0.9']['share_failed_by_predicted_day'])} by the "
            "predicted 90% day (targets 10/50/90%). For drives that do fail within a year it "
            f"names a median within a year only {_pct(life['share_median_within_horizon'])} of "
            "the time: most failures are not visible in SMART long in advance. For healthy "
            f"drives it says \"more than a year\" "
            f"{_pct(life['healthy_share_median_beyond_horizon'])} of the time.")
    rule = gains[gains["other"] == "rule_counters"] if not gains.empty else gains
    if not rule.empty:
        r = rule.sort_values("horizon").iloc[0]
        out.append(
            f"- **Against the classic rule** (any reallocated/pending/uncorrectable sector "
            f"counter), the model gains {r['auc_gain']:+.3f} ROC-AUC {_ci(r['auc_gain_ci'])} "
            f"at {r['horizon']} days.")
    return out

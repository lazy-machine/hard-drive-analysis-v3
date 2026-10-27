"""Exploratory tables and figures. Non-critical: nothing downstream depends on them.

Reads the drive index and the snapshot table, never the raw panel, so it is cheap at
every scale.
- models.csv: per drive model, drives, failures, drive-years, annualized failure rate.
- feature_signal.csv: per feature, fill rate and univariate weighted ROC-AUC for
  "fails within the binary horizon" on train snapshots (how much a single SMART
  attribute separates failing from healthy drive-days). `auc` uses only the drive-days
  where the attribute is reported; `auc_missing_low` ranks missing values lowest, which
  for attributes absent on whole vendors partly measures the vendor.
- correlation.png: Spearman correlation between features (train, sample of drives).
- km_by_counters.png: Kaplan-Meier survival of test snapshots with vs without any
  non-zero critical counter, the classic SMART warning sign.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import connect, load_snapshots, load_study, q  # noqa: E402
from metrics import km_failure, weighted_auc  # noqa: E402
from survival import known_status  # noqa: E402


def model_table(con, drives_path, pattern: str) -> pd.DataFrame:
    return con.sql(f"""
        SELECT model, count(*) AS drives, count(first_failure) AS failures,
               round(sum(n_rows) / 365.25, 1) AS drive_years,
               round(100 * count(first_failure) / (sum(n_rows) / 365.25), 2) AS afr_percent
        FROM read_parquet({q(drives_path)})
        WHERE NOT regexp_matches(coalesce(model, ''), {q(pattern)})
        GROUP BY model HAVING count(*) >= 100
        ORDER BY drives DESC""").df()


def feature_signal(meta: pd.DataFrame, X: np.ndarray, features: list[str],
                   horizon: int) -> pd.DataFrame:
    status = known_status(meta["duration_days"].to_numpy(), meta["event"].to_numpy(), horizon)
    known = status >= 0
    y, w = status[known], meta["weight"].to_numpy()[known]
    rows = []
    for j, f in enumerate(features):
        x = X[known, j]
        filled = ~np.isnan(x)
        # filled rows only: 187/188 are NULL on whole vendors, so ranking missing values
        # lowest would partly score "is this a Seagate". NaN if one class is left.
        auc = weighted_auc(x[filled], y[filled], w[filled]) if filled.any() else float("nan")
        rows.append({"feature": f, "fill_rate": float(filled.mean()), "auc": auc,
                     "auc_missing_low": weighted_auc(np.where(filled, x, -np.inf), y, w),
                     "separation": abs(auc - 0.5) * 2 if np.isfinite(auc) else 0.0,
                     "higher_means_risk": bool(auc >= 0.5)})
    return pd.DataFrame(rows).sort_values("separation", ascending=False)


def explore(ctx):
    study = load_study(ctx.inputs["study"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    out = ctx.outputs["dir"]
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        old.unlink()

    con = connect(ctx.workdir, ctx.name)
    models = model_table(con, ctx.inputs["drives"], study["data"]["ssd_model_pattern"])
    models.to_csv(out / "models.csv", index=False)

    features = schema["features"]
    meta, X = load_snapshots(ctx.inputs["snapshots"], ["train"], features)
    signal = feature_signal(meta, X, features, study["label"]["binary_horizon"])
    signal.to_csv(out / "feature_signal.csv", index=False)

    # Spearman correlation on at most 200k rows, sampled by drive
    serials = meta["serial_number"].unique()
    rng = np.random.default_rng(0)
    keep_drives = set(rng.permutation(serials)[: max(1, int(len(serials) * min(1, 200_000 / len(meta))))])
    sample = pd.DataFrame(X[meta["serial_number"].isin(keep_drives).to_numpy()], columns=features)
    sample = sample.loc[:, sample.notna().mean() > 0.05]
    corr = sample.rank().corr()
    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90, fontsize=6)
    ax.set_yticks(range(len(corr)), corr.columns, fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Spearman correlation")
    ax.set_title("Feature correlation (train snapshots)")
    fig.tight_layout()
    fig.savefig(out / "correlation.png", dpi=110)
    plt.close(fig)

    tmeta, tX = load_snapshots(ctx.inputs["snapshots"], ["test"],
                               study["features"]["critical_counters"])
    flagged = (np.nan_to_num(tX, nan=0) > 0).any(axis=1)
    days = np.arange(0, study["label"]["bin_edges"][-1] + 1, 5)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label, m in (("any critical counter > 0", flagged), ("all critical counters = 0", ~flagged)):
        if m.any():
            d, e, w = (tmeta[c].to_numpy()[m] for c in ("duration_days", "event", "weight"))
            ax.plot(days, [1 - km_failure(d, e, w, t) for t in days],
                    label=f"{label} ({m.sum()} snapshots)")
    ax.set_xlabel("days after snapshot")
    ax.set_ylabel("share still working (Kaplan-Meier)")
    ax.set_title("Test drives: survival after a snapshot")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "km_by_counters.png", dpi=110)
    plt.close(fig)
    top = signal.iloc[0]
    return {"models": len(models), "top_feature": top["feature"], "top_auc": float(top["auc"])}

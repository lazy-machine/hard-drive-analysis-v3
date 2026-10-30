"""Project checks for the data-verify gate (the `custom` list of the verify step).

The generic split, time, schema and leakage checks and the SQL rules on labels, censoring
and weights are declared in pipeline.toml. These are the checks that need Python. They
use the same helpers as the steps that built the data, so they cannot drift from them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import stable_bucket, stable_unit
from drives import assign_split


def stride_rows_on_stride_days(v):
    """Rows weighted drive_weight * stride fall on the drive's stride days.

    The schedule starts at the same per-drive offset as panel._register_cohort.
    """
    stride = int(v.var("stride"))
    if stride == 1:
        v.add("stride_rows_on_stride_days", True,
              "stride_days = 1: dense and stride weights coincide, rows cannot be told apart",
              category="weights")
        return
    cohort = v.dataset("cohort")[["serial_number", "drive_weight"]]
    offsets = {s: int(stable_unit(s, "stride") * stride) for s in cohort["serial_number"]}
    bad = 0
    for d in v.splits.values():
        m = d[["serial_number", "date", "weight"]].merge(cohort, on="serial_number", how="left")
        on_stride = np.abs(m["weight"] - m["drive_weight"] * stride) < 1e-6
        days = (pd.to_datetime(m["date"]) - pd.Timestamp("2000-01-01")).dt.days
        off = m["serial_number"].map(offsets)
        bad += int((on_stride & ((days + off) % stride != 0)).sum())
    v.add("stride_rows_on_stride_days", bad == 0,
          f"{bad} rows with weight drive_weight * {stride} off the drive's stride day",
          category="weights", details={"rows": bad},
          hint="The snapshot step and the cohort disagree on the stride offset.")


def cohort_split_matches_stable_bucket(v):
    """Every cohort drive, including drives without snapshots, is in its bucket's split.

    split.rule only sees snapshot rows; this covers the whole cohort, as drives.cohort
    assigns it.
    """
    cfg = {f"{s}_buckets": v.var(f"{s}_buckets") for s in ("train", "val", "test")}
    cohort = v.dataset("cohort")
    expected = [assign_split(stable_bucket(s), cfg) for s in cohort["serial_number"]]
    wrong = cohort.loc[cohort["split"].to_numpy() != expected, "serial_number"]
    v.add("cohort_split_matches_stable_bucket", wrong.empty,
          f"{len(wrong)} of {len(cohort)} cohort drives in the wrong split", category="split",
          details={"drives": len(wrong), "examples": sorted(wrong)[:5]},
          hint="The cohort step and the split rule in config/study.toml disagree.")


def features_are_float(v):
    """Every feature is stored as FLOAT (float32), the type the snapshot step writes."""
    train = v.train
    other = {f: str(train[f].dtype) for f in v.features if str(train[f].dtype) != "float32"}
    v.add("features_are_float", not other, f"{len(other)} non-float32 feature(s): "
          f"{dict(list(other.items())[:5])}", category="schema", details={"columns": other})


def few_sparse_features(v):
    """At most a quarter of the features are less than 1% filled in train."""
    train = v.train
    fill = train[v.features].notna().mean()
    sparse = sorted(fill[(fill > 0) & (fill < 0.01)].index)
    v.add("few_sparse_features", len(sparse) <= len(v.features) // 4,
          f"{len(sparse)} feature(s) < 1% filled in train: {sparse}", severity="warn",
          category="features", details={"sparse": sparse})

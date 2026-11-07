"""The arena's data: the dev cohort, and the files blocks and the harness read.

views() writes three directories:

- fit/: what a block may read while it trains. Train and early-stopping rows with labels.
- heldout/: what only the harness reads. Calibration and scoring rows, shuffled, features
  apart from labels, so a block's predict() gets features and nothing else.
- smoke/: the same layout on a small share of the drives, for quick tests.

Row spacing is a label leak: every day is kept in the 90 days before a failure and only
every 7th otherwise. That is why predict() never gets a drive id, a date or a weight.

History: for each row, the drive's values `lag` days earlier, for HIST_COLUMNS. A lag
takes the latest panel row at or before that day, so it never looks ahead of the row.
Values are signed log1p, in float16; NaN means the drive has no row that old.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from common import Progress, connect, load_snapshots, load_study, q, stable_unit, val_roles
from drives import assign_split

LAGS = [0, 1, 2, 3, 4, 5, 6, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365]
HIST_COLUMNS = [
    "smart_1_normalized", "smart_3_normalized", "smart_4_raw", "smart_5_raw",
    "smart_7_normalized", "smart_9_raw", "smart_10_raw", "smart_183_raw", "smart_184_raw",
    "smart_187_raw", "smart_189_raw", "smart_190_raw", "smart_192_raw", "smart_193_raw",
    "smart_194_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw", "smart_241_raw",
    "smart_242_raw",
]
META = ["serial_number", "date", "duration_days", "event", "weight"]
SMOKE_SHARE = 0.03
CHUNK = 400_000


def dev_cohort(ctx):
    """Drop the real test drives, re-split the rest by bucket, and hide everything after
    dev_end: last_date is capped there and a later failure is unknown."""
    split = load_study(ctx.inputs["study"])["split"]
    end = pd.Timestamp(split["dev_end"])
    cohort = pd.read_parquet(ctx.inputs["cohort"])
    cohort = cohort[cohort["split"] != "test"].reset_index(drop=True)
    cohort["split"] = [assign_split(b, split) for b in cohort["bucket"]]
    last = pd.to_datetime(cohort["last_date"]).clip(upper=end)
    failure = pd.to_datetime(cohort["failure_date"])
    cohort["last_date"] = last.dt.date
    cohort["failure_date"] = failure.where(failure <= end).dt.date
    cohort.to_parquet(ctx.outputs["cohort"], index=False)
    return {s: int(n) for s, n in cohort["split"].value_counts().items()}


def _panel(ctx, serials: pd.Series):
    """(sorted key per panel row, float32 values): key = drive code << 16 | day number."""
    con = connect(ctx.workdir, ctx.name)
    con.register("codes", pd.DataFrame({"serial_number": serials,
                                        "code": np.arange(len(serials), dtype=np.int64)}))
    glob = q(ctx.inputs["panel_dir"] / "*" / "*.parquet")
    cols = ", ".join(f'"{c}"' for c in HIST_COLUMNS)
    table = con.sql(
        f"""SELECT (c.code << 16) + date_diff('day', DATE '2000-01-01', p.date) AS key, {cols}
            FROM read_parquet({glob}, hive_partitioning = true) p JOIN codes c USING (serial_number)
            ORDER BY key""").fetch_arrow_table()
    keys = table.column("key").to_numpy()
    values = np.empty((table.num_rows, len(HIST_COLUMNS)), dtype=np.float32)
    for j, c in enumerate(HIST_COLUMNS):
        v = table.column(c).to_numpy(zero_copy_only=False).astype(np.float32)
        values[:, j] = np.sign(v) * np.log1p(np.abs(v))
    con.close()
    return keys, values


def _history(meta: pd.DataFrame, codes: pd.Series, keys, values, path: Path) -> None:
    n = len(meta)
    out = np.lib.format.open_memmap(path, mode="w+", dtype=np.float16,
                                    shape=(n, len(LAGS), len(HIST_COLUMNS)))
    code = meta["serial_number"].map(codes).to_numpy(np.int64)
    day = (meta["date"].to_numpy().astype("datetime64[D]")
           - np.datetime64("2000-01-01")).astype(np.int64)
    for lo in range(0, n, CHUNK):
        c, d = code[lo:lo + CHUNK], day[lo:lo + CHUNK]
        for i, lag in enumerate(LAGS):
            pos = np.searchsorted(keys, (c << 16) + d - lag, side="right") - 1
            ok = (pos >= 0) & ((keys[np.maximum(pos, 0)] >> 16) == c)
            block = values[np.maximum(pos, 0)]
            block[~ok] = np.nan
            out[lo:lo + CHUNK, i] = block
    out.flush()


def _write(root: Path, name: str, meta, X, codes, keys, values, labels_apart: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    np.save(root / f"{name}.X.npy", X)
    _history(meta, codes, keys, values, root / f"{name}.hist.npy")
    table = meta[META].reset_index(drop=True)
    table.to_parquet(root / (f"{name}.labels.parquet" if labels_apart else f"{name}.meta.parquet"),
                     index=False)


def _subset(meta, X, keep):
    return meta[keep].reset_index(drop=True), X[keep]


def _shuffled(meta, X, seed):
    order = np.random.default_rng(seed).permutation(len(meta))
    return meta.iloc[order].reset_index(drop=True), X[order]


def views(ctx):
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    features = schema["features"]
    out = ctx.outputs["dir"]
    shutil.rmtree(out, ignore_errors=True)

    serials = pd.read_parquet(ctx.inputs["cohort"], columns=["serial_number"])["serial_number"]
    codes = pd.Series(np.arange(len(serials), dtype=np.int64), index=serials.to_numpy())
    keys, values = _panel(ctx, serials)
    log(f"panel: {len(keys)} rows, {values.nbytes / 2**30:.1f} GiB")

    meta_tr, X_tr = load_snapshots(ctx.inputs["snapshots"], ["train"], features)
    meta_va, X_va = load_snapshots(ctx.inputs["snapshots"], ["val"], features)
    meta_sc, X_sc = load_snapshots(ctx.inputs["snapshots"], ["test"], features)
    role = val_roles(meta_va["serial_number"], study["split"]["calibration_share"])
    parts = {
        "train": ("fit", False, (meta_tr, X_tr)),
        "stop": ("fit", False, _subset(meta_va, X_va, ~role)),
        "cal": ("heldout", True, _shuffled(*_subset(meta_va, X_va, role), seed=1)),
        "score": ("heldout", True, _shuffled(meta_sc, X_sc, seed=2)),
    }
    smoke_drive = {s: stable_unit(s, "smoke") < SMOKE_SHARE for s in serials}
    manifest = {"features": features, "categorical": schema["categorical"],
                "groups": schema["groups"], "bin_edges": study["label"]["bin_edges"],
                "horizons": study["label"]["horizons"], "lags": LAGS,
                "hist_columns": HIST_COLUMNS, "split": study["split"], "rows": {}}
    for name, (where, apart, (meta, X)) in parts.items():
        _write(out / where, name, meta, X, codes, keys, values, apart)
        small = meta["serial_number"].map(smoke_drive).to_numpy()
        _write(out / "smoke" / where, name, *_subset(meta, X, small), codes, keys, values, apart)
        manifest["rows"][name] = len(meta)
        log(f"{name}: {len(meta)} rows, {int(meta['event'].sum())} event rows, "
            f"{meta['serial_number'].nunique()} drives; smoke {int(small.sum())} rows")
    for root in (out / "fit", out / "smoke" / "fit"):
        (root / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    return manifest["rows"]

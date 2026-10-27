"""Panel steps: pull the cohort's daily rows, then build sampled, labelled snapshots."""

from __future__ import annotations

import shutil
from datetime import date, timedelta

import pandas as pd
import pyarrow as pa

from common import (
    ID_COLUMNS, LABEL_COLUMNS, Progress, connect, left_truncated, load_sample, load_study,
    month_chunks, q, scalar, smart_columns, stable_unit, trend_columns, write_json,
)

# days_in_service counts from the drive's first row in the panel, which starts in 2016.
# left_truncated = 1 when that first row is the panel's first day, so the drive's real age is
# unknown (about 1 in 6 train drives, 1 in 50 test drives).
CONTEXT_FEATURES = ["days_in_service", "left_truncated", "capacity_tb", "model_code",
                    "vendor_code"]
VENDORS = ["HGST", "Seagate", "Toshiba", "WDC", "other"]


def _register_cohort(con, cohort: pd.DataFrame, batches: int, stride: int) -> None:
    """Expose the cohort to SQL with per-drive batch and stride offset (stable hashes)."""
    c = cohort.copy()
    c["batch"] = [int(stable_unit(s, "batch") * batches) for s in c["serial_number"]]
    c["stride_offset"] = [int(stable_unit(s, "stride") * stride) for s in c["serial_number"]]
    con.register("cohort_arrow", pa.Table.from_pandas(c, preserve_index=False))
    con.sql("CREATE TABLE cohort AS SELECT * FROM cohort_arrow")
    con.unregister("cohort_arrow")


def extract(ctx):
    """Every daily row of the cohort's drives, with the curated SMART columns as DOUBLE.

    - one row per (drive, day): same-day duplicates keep the most complete row, then the
      first filename (deterministic);
    - nothing after a drive's first failure (a re-deployed serial is not the same
      at-risk drive);
    - train/val drives stop at train_end. Test drives start max(trend window) days before
      test_start, so trend features on the first test day have history;
    - raw values listed in features.raw_low_bits keep only their low bits (vendor packing).

    TRY_CAST turns strings that are not numbers into NULL. Those are counted per column
    and returned, so an upstream format change shows up in the step result.

    Written as a directory partitioned by drive batch, so later steps can work on one
    batch at a time with bounded memory.
    """
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    cohort = pd.read_parquet(ctx.inputs["cohort"])
    src = ctx.inputs["panel"]
    out = ctx.outputs["panel_dir"]
    batches = ctx.params["batches"]
    shutil.rmtree(out, ignore_errors=True)

    tmp = ctx.workdir / "build" / "tmp" / ctx.name
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "extract.duckdb"
    db.unlink(missing_ok=True)
    con = connect(ctx.workdir, ctx.name, database=str(db))
    _register_cohort(con, cohort, batches, stride=1)

    cols = smart_columns(study)
    types = dict(con.sql(f"SELECT column_name, column_type FROM "
                         f"(DESCRIBE SELECT * FROM read_parquet({q(src)}))").fetchall())
    missing = [c for c in cols if c not in types]
    if missing:
        raise ValueError(f"panel is missing feature columns {missing}")
    max_window = max(study["features"]["trend_windows"])
    train_end = study["split"]["train_end"]
    test_from = date.fromisoformat(study["split"]["test_start"]) - timedelta(days=max_window)
    low_bits = study["features"].get("raw_low_bits", {})
    unknown = sorted(set(low_bits) - set(cols))
    if unknown:
        raise ValueError(f"features.raw_low_bits names columns that are not features: {unknown}")

    def cast(c):
        x = f'TRY_CAST(p."{c}" AS DOUBLE)'
        return f"fmod({x}, {float(2 ** low_bits[c])})" if c in low_bits else x

    casts = ", ".join(f'{cast(c)} AS "{c}"' for c in cols)
    # 1 when a non-NULL string did not parse as a number (only VARCHAR columns can fail)
    text_cols = [c for c in cols if types[c] == "VARCHAR"]
    bad = [f"bad_{i}" for i in range(len(text_cols))]
    bad_casts = "".join(f', (p."{c}" IS NOT NULL AND TRY_CAST(p."{c}" AS DOUBLE) IS NULL)::INT'
                        f' AS {b}' for c, b in zip(text_cols, bad, strict=True))
    completeness = " + ".join(f'(p."{c}" IS NOT NULL)::INT' for c in cols)
    col_list = ", ".join(f'"{c}"' for c in cols) + "".join(f", {b}" for b in bad)

    con.sql(f"""CREATE TABLE rows AS SELECT 0 AS batch, ''::VARCHAR AS serial_number,
                DATE '2000-01-01' AS date, {', '.join(f'0::DOUBLE AS "{c}"' for c in cols)}
                {''.join(f', 0::INT AS {b}' for b in bad)}
                LIMIT 0""")
    lo, hi = con.sql(f"SELECT min(date), max(date) FROM read_parquet({q(src)})").fetchall()[0]
    chunks = month_chunks(lo, hi, ctx.params.get("chunk_months", 1))
    for i, (a, b) in enumerate(chunks, 1):
        con.sql(f"""
            INSERT INTO rows
            SELECT batch, serial_number, date, {col_list} FROM (
                SELECT c.batch, p.serial_number, p.date, {casts}{bad_casts},
                       row_number() OVER (PARTITION BY p.serial_number, p.date
                                          ORDER BY {completeness} DESC, p.filename) AS rn
                FROM read_parquet({q(src)}) p
                JOIN cohort c USING (serial_number)
                WHERE p.date >= DATE '{a}' AND p.date < DATE '{b}'
                  AND (c.failure_date IS NULL OR p.date <= c.failure_date)
                  AND CASE WHEN c.split = 'test' THEN p.date >= DATE '{test_from}'
                           ELSE p.date <= DATE '{train_end}' END
            ) WHERE rn = 1""")
        if i % 12 == 0 or i == len(chunks):
            n_rows = scalar(con, "SELECT count(*) FROM rows")
            log(f"chunk {i}/{len(chunks)} ({a}) rows so far {n_rows}")

    n_rows = scalar(con, "SELECT count(*) FROM rows")
    n_drives = scalar(con, "SELECT count(DISTINCT serial_number) FROM rows")
    cast_failures = {}
    if bad:
        sums = con.sql("SELECT " + ", ".join(f"sum({b})" for b in bad) + " FROM rows").fetchall()[0]
        cast_failures = {c: int(v or 0) for c, v in zip(text_cols, sums, strict=True)}
        log(f"strings that are not numbers (now NULL): {cast_failures}")
        for b in bad:
            con.sql(f"ALTER TABLE rows DROP COLUMN {b}")
    con.sql(f"""COPY (SELECT * FROM rows ORDER BY batch, serial_number, date)
                TO {q(out)} (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (batch))""")
    con.close()
    db.unlink(missing_ok=True)
    log(f"wrote {n_rows} rows for {n_drives} drives")
    return {"rows": n_rows, "drives": n_drives, "cohort_drives": len(cohort),
            "cast_failures": cast_failures}


def model_levels(cohort: pd.DataFrame, top: int) -> list[str]:
    """Categorical levels for drive model, from train drives only (no test information)."""
    train = cohort[cohort["split"] == "train"]
    counts = train.groupby("model").size().reset_index(name="n")
    counts = counts.sort_values(["n", "model"], ascending=[False, True])
    return counts["model"].head(top).tolist()


def feature_schema(study: dict, levels: list[str]) -> dict:
    trends = trend_columns(study)
    windows = [f"window_days_{w}" for w in study["features"]["trend_windows"]]
    smart = smart_columns(study) + [name for name, _, _ in trends] + windows
    return {
        "features": CONTEXT_FEATURES + smart,
        "groups": {"context": CONTEXT_FEATURES, "smart": smart},
        "categorical": {"model_code": levels + ["other"], "vendor_code": VENDORS},
        "label": {"duration": "duration_days", "event": "event", "weight": "weight"},
    }


def snapshots(ctx):
    """Sampled drive-day snapshots with features and right-censored survival labels.

    Label: duration_days from the snapshot to the drive's first failure (event = 1) or to
    the last day it is known to be alive (event = 0, censored). Train/val drives are
    censored at train_end. A failure after train_end is unknown to training, never a
    "healthy" label.

    Sampling: within the split's time window, a snapshot every stride_days (drive-specific
    offset, weight stride_days) plus every day in the dense_days before a failure that is
    visible in the split (weight 1), times the drive's inverse sampling weight. A train
    drive failing after train_end gets no dense days, so its sampling does not depend on
    what happens after the cutoff.
    """
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    scale = load_sample(ctx.inputs["sample"])
    cohort = pd.read_parquet(ctx.inputs["cohort"])
    batches = sorted(int(p.name.split("=")[1]) for p in ctx.inputs["panel_dir"].glob("batch=*"))
    if not batches:
        raise ValueError(f"no batch=* partitions in {ctx.inputs['panel_dir']}")
    stride, dense = scale["stride_days"], scale["dense_days"]

    levels = model_levels(cohort, study["features"]["top_models"])
    schema = feature_schema(study, levels)
    cohort = cohort.assign(
        left_truncated=left_truncated(cohort["first_date"]),
        model_code=[levels.index(m) if m in levels else len(levels) for m in cohort["model"]],
        vendor_code=[VENDORS.index(v) for v in cohort["vendor"]],
    )

    con = connect(ctx.workdir, ctx.name)
    _register_cohort(con, cohort, len(batches), stride)
    split = study["split"]
    trends = trend_columns(study)
    windows = study["features"]["trend_windows"]
    window_defs = ", ".join(
        f"w{w} AS (PARTITION BY serial_number ORDER BY date "
        f"RANGE BETWEEN INTERVAL {w} DAYS PRECEDING AND CURRENT ROW)" for w in windows)
    trend_sql = ", ".join(
        f'"{src}" - first_value("{src}" IGNORE NULLS) OVER w{w} AS "{name}"'
        for name, src, w in trends)
    span_sql = ", ".join(
        f"date_diff('day', first_value(date) OVER w{w}, date) AS window_days_{w}" for w in windows)
    smart_sql = ", ".join(f'"{c}"' for c in smart_columns(study))
    feature_sql = ", ".join(f'"{f}"::FLOAT AS "{f}"' for f in schema["features"])

    parts = ctx.workdir / "build" / "tmp" / ctx.name / "parts"
    shutil.rmtree(parts, ignore_errors=True)
    parts.mkdir(parents=True)
    panel_glob = q(ctx.inputs["panel_dir"] / "*" / "*.parquet")
    for i, b in enumerate(batches, 1):
        con.sql(f"""
        COPY (
        WITH f AS (
            SELECT p.serial_number, p.date, {smart_sql}, {trend_sql}, {span_sql}
            FROM read_parquet({panel_glob}, hive_partitioning = true) p
            WHERE p.batch = {b}
            WINDOW {window_defs}
        ), labelled AS (
            SELECT f.*, c.split, c.drive_weight, c.failure_date, c.stride_offset,
                   date_diff('day', c.first_date, f.date) AS days_in_service,
                   c.left_truncated, c.capacity_bytes / 1e12 AS capacity_tb, c.model_code,
                   c.vendor_code,
                   CASE WHEN c.split = 'test' THEN c.last_date
                        ELSE least(c.last_date, DATE '{split['train_end']}') END AS censor_date
            FROM f JOIN cohort c USING (serial_number)
        ), sampled AS (
            SELECT *,
                   failure_date IS NOT NULL AND failure_date <= censor_date
                       AND date_diff('day', date, failure_date) < {dense} AS in_dense,
                   (date_diff('day', DATE '2000-01-01', date) + stride_offset) % {stride} = 0
                       AS on_stride,
                   failure_date IS NOT NULL AND failure_date <= censor_date AS event
            FROM labelled
            WHERE CASE WHEN split = 'test' THEN date >= DATE '{split['test_start']}'
                       ELSE date <= DATE '{split['train_end']}' END
        )
        SELECT serial_number, date, split,
               date_diff('day', date,
                         CASE WHEN event THEN failure_date ELSE censor_date END) AS duration_days,
               event::INT AS event,
               (drive_weight * CASE WHEN in_dense THEN 1 ELSE {stride} END)::DOUBLE AS weight,
               {feature_sql}
        FROM sampled
        WHERE in_dense OR on_stride
        ) TO {q(parts / f'part-{b:03d}.parquet')} (FORMAT PARQUET)""")
        log(f"batch {i}/{len(batches)}")

    con.sql(f"""COPY (SELECT * FROM read_parquet({q(parts / '*.parquet')})
                      ORDER BY split, serial_number, date)
                TO {q(ctx.outputs['snapshots'])} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    shutil.rmtree(parts, ignore_errors=True)
    write_json(ctx.outputs["schema"], schema)

    out = q(ctx.outputs["snapshots"])
    stats = {
        f"{s}": n for s, n in con.sql(
            f"SELECT split, count(*) FROM read_parquet({out}) GROUP BY split").fetchall()}
    stats["events"] = scalar(con, f"SELECT sum(event) FROM read_parquet({out})")
    stats["features"] = len(schema["features"])
    log(stats)
    columns = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet({out})").fetchall()]
    if columns != ID_COLUMNS + LABEL_COLUMNS + schema["features"]:
        raise RuntimeError(f"snapshot columns do not match the schema: {columns}")
    return stats

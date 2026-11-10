"""Drive-level steps: index every drive in the panel, then pick the study cohort."""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from common import (
    MODEL_SQL, Progress, connect, load_sample, load_study, month_chunks, q, scalar,
    stable_bucket, stable_unit, write_json,
)


def drive_index(ctx):
    """One row per serial number: model, capacity, observed span and first failure.

    Model and capacity become snapshot features, so neither may depend on how long the
    drive lives. Both are read from the drive's first rows:

    - model: the first one the drive reported (7 drives change model string mid-life).
    - capacity: the first valid value, rounded to 10 GB. Rounding absorbs a few MB of
      jitter and the rounded values of 2018-02-25 (4,000,790,000,000 instead of
      4,000,787,030,016 for every live drive); a lifetime maximum of the unrounded value
      told the model which drives were alive on that day. 94,816 drives report -1 on
      their first day and a valid capacity from the next, so a first-day snapshot takes
      the next day's value: capacity is a nameplate fact the operator knows at install.
      The 10 drives that never report one all fail within days, so they get their
      model's most common capacity instead of a NULL that would mark them.

    The log counts drives whose rounded capacity varies, to catch a dataset where the
    first value is not the nameplate (12 drives briefly report 2^37 bytes, always after
    their true value).

    The panel is sorted by date, so it is aggregated one calendar chunk at a time and
    the partial aggregates are merged. A single GROUP BY over all 646M rows spills tens
    of GB on a 15 GB machine, while monthly chunks take a few seconds each.
    """
    log = Progress(ctx)
    src = ctx.inputs["panel"]
    if expected := ctx.params.get("sha256"):
        _check_sha256(src, expected, log)
    con = connect(ctx.workdir, ctx.name)
    lo, hi = con.sql(f"SELECT min(date), max(date) FROM read_parquet({q(src)})").fetchall()[0]
    chunks = month_chunks(lo, hi, ctx.params.get("chunk_months", 1))
    log(f"panel {lo}..{hi}, {len(chunks)} chunks")

    con.sql("""CREATE TABLE part (
        serial_number VARCHAR, model VARCHAR, model_date DATE, n_models BIGINT,
        capacity_bytes DOUBLE, capacity_date DATE, capacity_min DOUBLE, capacity_max DOUBLE,
        first_date DATE, last_date DATE, n_rows BIGINT,
        n_failure_rows BIGINT, first_failure DATE, last_failure DATE)""")
    for i, (a, b) in enumerate(chunks, 1):
        con.sql(f"""
            INSERT INTO part
            WITH r AS (
                SELECT *, {MODEL_SQL} AS m,
                       CASE WHEN capacity_bytes > 0
                            THEN round(capacity_bytes / 1e10) * 1e10 END AS cap
                FROM read_parquet({q(src)})
                WHERE date >= DATE '{a}' AND date < DATE '{b}')
            SELECT serial_number,
                   arg_min(m, {{'d': date, 'm': m}}), min(date), count(DISTINCT m),
                   arg_min(cap, {{'d': date, 'c': cap}}) FILTER (WHERE cap IS NOT NULL),
                   min(date) FILTER (WHERE cap IS NOT NULL), min(cap), max(cap),
                   min(date), max(date), count(*), sum(failure),
                   min(CASE WHEN failure = 1 THEN date END),
                   max(CASE WHEN failure = 1 THEN date END)
            FROM r
            GROUP BY serial_number""")
        if i % 12 == 0 or i == len(chunks):
            log(f"chunk {i}/{len(chunks)} ({a})")

    con.sql("""
        CREATE TABLE merged AS
        SELECT serial_number,
               arg_min(model, {'d': model_date, 'm': model}) AS model,
               max(n_models) AS n_models_per_month,
               arg_min(capacity_bytes, {'d': capacity_date, 'c': capacity_bytes})
                   AS capacity_bytes,
               min(capacity_min) AS capacity_min, max(capacity_max) AS capacity_max,
               min(first_date) AS first_date,
               max(last_date) AS last_date,
               sum(n_rows)::BIGINT AS n_rows,
               sum(n_failure_rows)::BIGINT AS n_failure_rows,
               min(first_failure) AS first_failure,
               max(last_failure) AS last_failure
        FROM part GROUP BY serial_number""")
    varies, missing = con.sql("""SELECT count(*) FILTER (WHERE capacity_min <> capacity_max),
                                        count(*) FILTER (WHERE capacity_bytes IS NULL)
                                 FROM merged""").fetchall()[0]
    log(f"rounded capacity varies on {varies} drives; {missing} report none (model's used)")
    con.sql(f"""
        COPY (
            WITH counts AS (
                SELECT model, capacity_bytes, count(*) AS n FROM merged
                WHERE capacity_bytes IS NOT NULL GROUP BY ALL
            ), usual AS (
                SELECT model, arg_max(capacity_bytes, {{'n': n, 'c': capacity_bytes}}) AS cap
                FROM counts GROUP BY model
            )
            SELECT m.serial_number, m.model, m.n_models_per_month,
                   coalesce(m.capacity_bytes, u.cap) AS capacity_bytes,
                   m.first_date, m.last_date, m.n_rows, m.n_failure_rows,
                   m.first_failure, m.last_failure
            FROM merged m LEFT JOIN usual u USING (model)
            ORDER BY m.serial_number
        ) TO {q(ctx.outputs['drives'])} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    out = q(ctx.outputs["drives"])
    n, failed = con.sql(f"""SELECT count(*), count(first_failure)
                           FROM read_parquet({out})""").fetchall()[0]
    rows = scalar(con, f"SELECT sum(n_rows) FROM read_parquet({out})")
    log(f"{n} drives, {failed} with a failure, {rows} rows")
    return {"drives": n, "failed": failed, "rows": rows, "capacity_varies": varies,
            "capacity_missing": missing}


def _check_sha256(path, expected: str, log, chunk: int = 8 * 2**20) -> None:
    """Refuse to index a panel file that is not the one pipeline.toml names."""
    size = os.path.getsize(path)
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
            done += len(block)
            if done % 2**32 == 0:  # a line every 4 GiB
                log(f"sha256 {done / 2**30:.0f}/{size / 2**30:.0f} GiB")
    actual = h.hexdigest()
    if actual != expected.lower():
        raise ValueError(f"{path}: sha256 is {actual}, pipeline.toml expects {expected}")
    log(f"sha256 ok ({actual})")


def assign_split(bucket: int, split_cfg: dict) -> str:
    for name in ("train", "val", "test"):
        lo, hi = split_cfg[f"{name}_buckets"]
        if lo <= bucket < hi:
            return name
    raise ValueError(f"bucket {bucket} is in no split")


def select_cohort(drives: pd.DataFrame, study: dict, scale: dict) -> tuple[pd.DataFrame, dict]:
    """Choose the drives of this run and give each a split and an inverse-probability weight.

    Pure function of its inputs (no I/O), so it is unit-tested directly.
    """
    split_cfg = study["split"]
    train_end = pd.Timestamp(split_cfg["train_end"])
    test_start = pd.Timestamp(split_cfg["test_start"])
    d = drives.copy()
    for col in ("first_date", "last_date", "first_failure"):
        d[col] = pd.to_datetime(d[col])
    counts = {"panel_drives": len(d)}

    is_ssd = d["model"].fillna("").str.contains(study["data"]["ssd_model_pattern"], regex=True)
    counts["excluded_ssd"] = int(is_ssd.sum())
    d = d[~is_ssd]

    d["bucket"] = [stable_bucket(s) for s in d["serial_number"]]
    d["split"] = [assign_split(b, split_cfg) for b in d["bucket"]]
    d["failure_date"] = d["first_failure"]
    # A drive must be observable in its split's time window. Train/val drives need rows
    # on or before train_end. Test drives need rows from test_start on and must not have
    # failed before test_start (then they have no test snapshot).
    in_train_window = d["first_date"] <= train_end
    in_test_window = (d["last_date"] >= test_start) & (
        d["failure_date"].isna() | (d["failure_date"] >= test_start))
    eligible = np.where(d["split"] == "test", in_test_window, in_train_window)
    counts["excluded_outside_window"] = int((~eligible).sum())
    d = d[eligible].copy()

    # Stratified sampling. The stratum uses the whole panel ("fails at some point"), which
    # is fine for inverse-probability weighting: the weight is the true inclusion odds.
    d["stratum"] = np.where(d["failure_date"].notna(), "failing", "healthy")
    fraction = np.where(d["stratum"] == "failing",
                        scale["failing_fraction"], scale["healthy_fraction"])
    u = np.array([stable_unit(s, "sample") for s in d["serial_number"]])
    keep = u < fraction
    d["drive_weight"] = 1.0 / fraction
    d = d[keep]

    d["model"] = d["model"].fillna("unknown")
    d["vendor"] = [_vendor(m) for m in d["model"]]
    d["n_post_failure_days"] = np.where(
        d["failure_date"].notna(), (d["last_date"] - d["failure_date"]).dt.days, 0)
    cols = ["serial_number", "split", "bucket", "stratum", "drive_weight", "model", "vendor",
            "n_models_per_month", "capacity_bytes", "first_date", "last_date", "failure_date",
            "n_post_failure_days"]
    cohort = d[cols].sort_values("serial_number").reset_index(drop=True)
    for col in ("first_date", "last_date", "failure_date"):
        cohort[col] = cohort[col].dt.date

    counts["cohort_drives"] = len(cohort)
    counts["by_split_stratum"] = {
        f"{s}/{t}": int(n) for (s, t), n in cohort.groupby(["split", "stratum"]).size().items()}
    counts["drives_reporting_after_failure"] = int((cohort["n_post_failure_days"] > 0).sum())
    # A serial reported under two model strings in one month is likely two drives.
    counts["drives_with_several_models"] = int((cohort["n_models_per_month"] > 1).sum())
    return cohort, counts


def _vendor(model: str) -> str:
    if model.startswith(("ST", "Seagate")):
        return "Seagate"
    if model.startswith("TOSHIBA"):
        return "Toshiba"
    if model.startswith(("HGST", "Hitachi")):
        return "HGST"
    if model.startswith(("WDC", "WD", "WUH")):
        return "WDC"
    return "other"


def cohort(ctx):
    study = load_study(ctx.inputs["study"])
    scale = load_sample(ctx.inputs["sample"])
    drives = pd.read_parquet(ctx.inputs["drives"])
    table, counts = select_cohort(drives, study, scale)
    pq.write_table(pa.Table.from_pandas(table, preserve_index=False), ctx.outputs["cohort"],
                   compression="zstd")
    write_json(ctx.outputs["summary"], {"scale": scale, **counts})
    by = counts["by_split_stratum"]
    return {"scale": scale["scale"], "drives": len(table),
            "failing": sum(v for k, v in by.items() if k.endswith("failing"))}

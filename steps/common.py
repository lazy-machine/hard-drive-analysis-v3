"""Shared helpers: the study contract, stable hashing, DuckDB connections, progress logs.

Every step module imports this file and lists it under ``watch`` in pipeline.toml, so a
change here invalidates the steps that use it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import tomllib
from pathlib import Path
from typing import Any

import duckdb

# Columns of the snapshot table that are not model features. Anything in this list, or
# derived from the future of a snapshot, must never reach a model (checked by verify).
ID_COLUMNS = ["serial_number", "date", "split"]
LABEL_COLUMNS = ["duration_days", "event", "weight"]
LEAK_COLUMNS = ID_COLUMNS + LABEL_COLUMNS + [
    "failure", "failure_date", "censor_date", "last_date", "first_date", "date_days",
]
SPLITS = ("train", "val", "test")


# -- contract --------------------------------------------------------------------------

def load_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_study(path: Path) -> dict[str, Any]:
    """Load config/study.toml and check that its rules are consistent."""
    study = load_toml(path)
    split = study["split"]
    ranges = [split["train_buckets"], split["val_buckets"], split["test_buckets"]]
    covered = sorted(b for lo, hi in ranges for b in range(lo, hi))
    if covered != list(range(100)):
        raise ValueError(f"split buckets must cover 0-99 exactly once, got {ranges}")
    if split["test_start"] <= split["train_end"]:
        raise ValueError("split.test_start must be after split.train_end")

    label = study["label"]
    edges = label["bin_edges"]
    if edges[0] != 0 or edges != sorted(set(edges)):
        raise ValueError(f"label.bin_edges must start at 0 and increase, got {edges}")
    missing = [h for h in label["horizons"] + [label["binary_horizon"]] if h not in edges]
    if missing:
        raise ValueError(f"horizons {missing} are not bin edges {edges}")
    return study


def load_sample(path: Path) -> dict[str, Any]:
    """The active scale from config/sample.toml, with its name under 'scale'."""
    cfg = load_toml(path)
    name = cfg["scale"]
    if name not in cfg["scales"]:
        raise ValueError(f"scale '{name}' is not defined (have {sorted(cfg['scales'])})")
    scale = dict(cfg["scales"][name], scale=name)
    for key in ("failing_fraction", "healthy_fraction"):
        if not 0 < scale[key] <= 1:
            raise ValueError(f"{key} must be in (0, 1], got {scale[key]}")
    if scale["stride_days"] < 1 or scale["dense_days"] < 0:
        raise ValueError("stride_days must be >= 1 and dense_days >= 0")
    return scale


def smart_columns(study: dict[str, Any]) -> list[str]:
    """SMART value columns, in a fixed order. This list *is* the frozen feature schema."""
    feats = study["features"]
    cols = [f"smart_{a}_raw" for a in feats["raw"]]
    cols += [f"smart_{a}_normalized" for a in feats["normalized"]]
    return cols


def trend_columns(study: dict[str, Any]) -> list[tuple[str, str, int]]:
    """(feature name, source column, window days) for every trend feature."""
    feats = study["features"]
    known = set(smart_columns(study))
    unknown = [c for c in feats["trend"] if c not in known]
    if unknown:
        raise ValueError(f"trend columns {unknown} are not in features.raw/normalized")
    return [(f"{c}_d{w}", c, w) for w in feats["trend_windows"] for c in feats["trend"]]


# -- stable hashing --------------------------------------------------------------------

def stable_unit(serial: str, salt: str) -> float:
    """A uniform number in [0, 1) derived from sha256(salt:serial).

    DuckDB's hash() is not stable across versions, so splits and samples are computed
    here. Different salts give independent draws for the same drive.
    """
    digest = hashlib.sha256(f"{salt}:{serial}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def stable_bucket(serial: str) -> int:
    """The drive's split bucket in 0-99."""
    return int(stable_unit(serial, "split") * 100)


def left_truncated(first_date):
    """1 for drives whose first row is the cohort's first panel day: they were already in
    service when the panel starts, so days_in_service understates their age."""
    import pandas as pd

    first = pd.to_datetime(pd.Series(first_date))
    return (first <= first.min()).astype(int).to_numpy()


def val_roles(serials, share: float):
    """True for validation drives that calibrate (and set the alert threshold), False for
    those that only drive early stopping. A stable hash, independent of the split hash."""
    import numpy as np

    return np.array([stable_unit(s, "val_role") < share for s in serials], dtype=bool)


# -- SQL helpers -----------------------------------------------------------------------

def q(path: Path | str) -> str:
    """A path or string as a SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


# Model strings differ only in whitespace across years ("WDC  WUH721414ALE6L4").
MODEL_SQL = "regexp_replace(trim(model), '\\s+', ' ', 'g')"



def month_chunks(start, end, months: int) -> list[tuple[str, str]]:
    """[lo, hi) ISO date ranges covering start..end in steps of `months` calendar months."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        ny, nm = y + (m - 1 + months) // 12, (m - 1 + months) % 12 + 1
        out.append((f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"))
        y, m = ny, nm
    return out


def connect(workdir: Path, name: str, memory_fraction: float = 0.6,
            database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """A DuckDB connection sized to this machine, spilling to build/tmp/<name>.

    HDA_MEMORY_FRACTION and HDA_THREADS override the defaults. They change speed and peak
    memory, never results, so they are environment variables and not checkpointed params.
    """
    fraction = float(os.environ.get("HDA_MEMORY_FRACTION", memory_fraction))
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    threads = int(os.environ.get("HDA_THREADS", os.cpu_count() or 4))
    tmp = workdir / "build" / "tmp" / name
    tmp.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(database, config={
        "memory_limit": f"{total * fraction / 2**30:.1f}GiB",
        "threads": threads,
        "temp_directory": str(tmp),
        "preserve_insertion_order": False,
    })


def available_memory() -> int:
    """Bytes the system can give us now (MemAvailable counts reclaimable page cache)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    return con.sql(sql).fetchall()[0][0]


def load_snapshots(path: Path, splits: list[str], features: list[str]):
    """(meta DataFrame, float32 feature matrix) for the given splits, in file order.

    Columns are copied one at a time into a preallocated matrix, so peak memory is about
    one matrix plus one column.
    """
    import numpy as np
    import pandas as pd

    con = duckdb.connect(config={"threads": int(os.environ.get("HDA_THREADS", os.cpu_count() or 4))})
    where = "split IN (" + ", ".join(q(s) for s in splits) + ")"
    cols = ", ".join(f'"{c}"' for c in ID_COLUMNS + LABEL_COLUMNS + features)
    table = con.sql(f"SELECT {cols} FROM read_parquet({q(path)}) WHERE {where} "
                    "ORDER BY split, serial_number, date").fetch_arrow_table()
    X = np.empty((table.num_rows, len(features)), dtype=np.float32)
    for j, f in enumerate(features):
        X[:, j] = table.column(f).to_numpy(zero_copy_only=False)
    meta = pd.DataFrame({c: table.column(c).to_numpy(zero_copy_only=False)
                         for c in ID_COLUMNS + LABEL_COLUMNS})
    del table
    return meta, X


# -- outputs and progress --------------------------------------------------------------

def write_json(path: Path, obj: Any) -> None:
    """Deterministic JSON (sorted keys), so unchanged results keep later steps cached."""
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


class Progress:
    """Timestamped progress lines in build/logs/<step>.log.

    data-pipeline captures worker stdout and shows it only at the end, so a long
    full-scale step would otherwise be silent. `tail -f build/logs/<step>.log` follows it.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.t0 = time.perf_counter()
        log_dir = ctx.workdir / "build" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{ctx.name}.log"
        self.path.write_text("")

    def __call__(self, *parts: Any) -> None:
        line = f"[{time.perf_counter() - self.t0:8.1f}s] " + " ".join(map(str, parts))
        with self.path.open("a") as fh:
            fh.write(line + "\n")
        self.ctx.log(*parts)

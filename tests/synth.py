"""A small synthetic Backblaze-style panel with known answers.

It reproduces the quirks the pipeline must handle: an SSD model, whitespace variants of a
model name, gaps in daily reporting, same-day duplicate rows, a drive that keeps
reporting after its failure, VARCHAR-typed SMART columns, a day of rounded capacities, a
model string that changes mid-life, and failures on both sides of the train/test cutoff.
Failing drives show a rising reallocated-sector count (smart_5) in their last weeks, so a
working model must find signal.

Vendor quirks from the real panel: Seagate packs fields into the raw values of 188 and 240
(huge numbers on a few rows), the other vendors report 187 and 188 as NULL, a VARCHAR
column holds an occasional non-numeric string, and one failing drive in ten is silent (no
counter ever moves before it fails).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

START, END = date(2022, 6, 1), date(2024, 9, 30)
MODELS = ["ST4000DM000", "TOSHIBA MG07ACA14TA", "WDC WUH721414ALE6L4", "HGST HMS5C4040BLE640"]
VARCHAR_COLUMNS = ["smart_22_raw", "smart_24_normalized"]
SEAGATE_ONLY = ["smart_187_raw", "smart_187_normalized", "smart_188_raw", "smart_188_normalized"]
COUNTERS = ["smart_187_raw", "smart_188_raw", "smart_198_raw"]  # zero on a healthy drive
# After the invariance test's cutoff: one day of rounded capacities for every drive (the real
# panel has one, 2018-02-25), and some drives that report a new model string from this day.
ROUNDED_DAY = RENAME_DAY = date(2024, 6, 1)


def silent(serial: str) -> bool:
    """Failing drives that give no SMART warning before they fail."""
    return int(serial[3:]) % 10 == 7


def make_panel(columns: list[str], n_drives: int = 360, seed: int = 8) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = (END - START).days + 1
    rows = []
    for i in range(n_drives):
        serial = f"SYN{i:05d}"
        model = MODELS[i % len(MODELS)]
        if i % 50 == 3:
            model = "CT250MX500SSD1"                   # boot SSD: must be excluded
        start = int(rng.integers(0, 200))
        end = days - 1 - int(rng.integers(0, 60)) if rng.random() < 0.3 else days - 1
        fail_day = None
        if rng.random() < 0.3:
            fail_day = int(rng.integers(start + 40, end + 1))
        hours0 = float(rng.integers(1_000, 40_000))
        seagate = model.startswith("ST")
        for t in range(start, (fail_day if fail_day is not None else end) + 1):
            if rng.random() < 0.03:                    # reporting gap
                continue
            d = START + timedelta(days=t)
            to_fail = None if fail_day is None else fail_day - t
            realloc = 0.0
            if to_fail is not None and to_fail < 45 and not silent(serial):
                realloc = float((45 - to_fail) * rng.integers(1, 4))
            values = {c: float(rng.integers(0, 3)) for c in columns}
            values.update({c: 0.0 for c in COUNTERS})
            values.update({
                "smart_5_raw": realloc, "smart_197_raw": realloc / 2,
                "smart_9_raw": hours0 + 24 * t, "smart_194_raw": float(rng.integers(25, 45)),
                "smart_5_normalized": 100.0 - min(realloc, 99),
                "smart_240_raw": hours0 + 24 * t,
            })
            if seagate:
                if rng.random() < 0.03:                # packed 16-bit fields, not a count
                    values["smart_188_raw"] = float(rng.integers(1, 800)) * 2**32
                if rng.random() < 0.02:                # milliseconds above bit 32
                    values["smart_240_raw"] += float(rng.integers(1, 2**24)) * 2**32
            else:
                values.update({c: None for c in SEAGATE_ONLY if c in values})
            m = model
            if model.startswith("WDC") and d.year == 2022:
                m = model.replace("WDC ", "WDC  ")     # whitespace variant of the same model
            if model.startswith("HGST") and i % 8 == 7 and d >= RENAME_DAY:
                m = "HGST HMS5C4040ALE640"             # model string changes mid-life
            capacity = 4_000_787_030_016 if d != ROUNDED_DAY else 4_000_790_000_000
            rows.append({"date": d, "serial_number": serial, "model": m,
                         "capacity_bytes": capacity if "SSD" not in m else 2.5e11,
                         "failure": int(to_fail == 0), "filename": f"{d}.csv", **values})
            if rng.random() < 0.01:                    # same-day duplicate, less complete
                dup = dict(rows[-1], filename=f"{d}-b.csv", smart_194_raw=None)
                rows.append(dup)
        if i == 11 and fail_day is not None:           # keeps reporting after failure
            for t in range(fail_day + 1, min(fail_day + 5, days)):
                d = START + timedelta(days=t)
                rows.append({**rows[-1], "date": d, "failure": 0, "filename": f"{d}.csv"})
    df = pd.DataFrame(rows)
    for c in VARCHAR_COLUMNS:
        df[c] = df[c].map(lambda v: None if pd.isna(v) else str(int(v)))
    df.loc[df.index % 997 == 5, VARCHAR_COLUMNS[0]] = "n/a"   # not a number: TRY_CAST -> NULL
    return df.sort_values(["date", "serial_number"]).reset_index(drop=True)

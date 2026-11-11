"""The evaluation sections added for the article review: full follow-up, per-drive
alerts, calibration by group and seed replicates, on small hand-made test sets."""

import numpy as np
import pandas as pd

from common import stable_unit
from evaluate import (
    Drives, _groups, alerting, full_follow_up, on_stride, seed_spread, split_seeds,
    weekly_alerts,
)

END = pd.Timestamp("2025-12-31")


def _frame(rows):
    """rows: (serial, date, duration_days, event, score, stratum, model, vendor, cap_tb)."""
    df = pd.DataFrame(rows, columns=["serial_number", "date", "duration_days", "event", "s",
                                     "stratum", "model", "vendor", "cap_tb"])
    df["date"] = pd.to_datetime(df["date"])
    df["weight"] = 1.0
    df["drive_weight"] = 1.0
    df["capacity_bytes"] = df["cap_tb"] * 1e12
    df["last_date"] = END
    df["m__p30"] = df["s"]
    df["m__p7"] = df["s"]
    return df


def test_split_seeds():
    models = {"hazard_smart": {}, "hazard_smart_seed1": {}, "binary_30d_seed2": {}, "rule": {}}
    main, seeds = split_seeds(models)
    assert set(main) == {"hazard_smart", "rule"}
    assert set(seeds) == {"hazard_smart_seed1", "binary_30d_seed2"}


def test_full_follow_up_drops_snapshots_near_the_panel_end():
    rows = []
    # early snapshots: one failure within 30 days, three survivors
    rows += [("a", "2025-01-01", 10, 1, 0.9, "failing", "X", "V", 4),
             ("b", "2025-01-01", 300, 0, 0.1, "healthy", "X", "V", 4),
             ("c", "2025-01-01", 300, 0, 0.2, "healthy", "X", "V", 4),
             ("d", "2025-01-01", 300, 0, 0.3, "healthy", "X", "V", 4)]
    # 10 days before the end: a failure (known) and a survivor (unknown at 30 days)
    rows += [("e", "2025-12-21", 5, 1, 0.8, "failing", "X", "V", 4),
             ("f", "2025-12-21", 10, 0, 0.05, "healthy", "X", "V", 4)]
    test = _frame(rows)
    D = Drives(test)
    models = {"m": {"kind": "binary", "horizons": [30]}}
    out, _ = full_follow_up(test, D, models, [30], "m", rounds=5, seed=1, log=lambda m: None)
    (r,) = out
    assert r["snapshots"] == 4                 # e and f are dated too late
    assert r["positive_snapshots"] == 1
    assert np.isclose(r["base_rate"], 0.25)
    assert r["last_snapshot_date"] == "2025-01-01"


def test_alerting_counts_nonfailing_drives():
    rows = []
    # failing drive alerted in its last 30 days
    rows += [("a", "2025-01-01", 5, 1, 0.99, "failing", "X", "V", 4)]
    # four non-failing drives with two snapshots each; one of them alerts once
    for k, s in enumerate(["p", "q", "r", "t"]):
        hi = 0.97 if k == 0 else 0.1
        rows += [(s, "2025-01-01", 300, 0, 0.1, "healthy", "X", "V", 4),
                 (s, "2025-01-08", 293, 0, hi, "healthy", "X", "V", 4)]
    test = _frame(rows)
    val = _frame([(f"v{i}", "2023-01-01", 300, 0, i / 100, "healthy", "X", "V", 4)
                  for i in range(100)])
    D = Drives(test)
    models = {"m": {"kind": "binary", "horizons": [30]}}
    summary, _ = alerting(val, test, D, models, 30, [0.05], 0.05, 7, [0, 7, 30], 5, 1)
    (a,) = summary
    assert a["nonfailing_drives"] == 4 and a["nonfailing_drives_alerted"] == 1
    assert np.isclose(a["share_nonfailing_drives_alerted"], 0.25)
    assert np.isclose(a["nonfailing_alerted_per_failing_alerted"], 1.0)


def test_groups_split_the_firmware_model_from_its_vendor():
    day = "2025-01-01"
    test = _frame([("a", day, 5, 1, 0.9, "failing", "TOSHIBA MG08ACA16TEY", "Toshiba", 16),
                   ("b", day, 300, 0, 0.1, "healthy", "TOSHIBA MG07", "Toshiba", 14),
                   ("c", day, 300, 0, 0.1, "healthy", "ST4000", "Seagate", 4)])
    g = _groups(test, 16, "MG08ACA16TEY")
    assert g["model MG08ACA16TEY"].tolist() == [True, False, False]
    assert g["vendor Toshiba without MG08ACA16TEY"].tolist() == [False, True, False]
    assert g["capacity >= 16 TB"].tolist() == [True, False, False]
    assert "model NOPE" not in _groups(test, 16, "NOPE")


def test_seed_spread_pairs_replicates():
    rows = [("a", "2025-01-01", 5, 1, 0.9, "failing", "X", "V", 4),
            ("b", "2025-01-01", 300, 0, 0.1, "healthy", "X", "V", 4),
            ("c", "2025-01-01", 300, 0, 0.5, "healthy", "X", "V", 4)]
    test = _frame(rows)
    cols = {"hazard_smart": [0.9, 0.1, 0.5], "hazard_smart_seed1": [0.4, 0.1, 0.5],
            "binary_30d": [0.9, 0.1, 0.5], "binary_30d_seed1": [0.9, 0.1, 0.5]}
    for name, col in cols.items():
        test[f"{name}__p30"] = col
    D = Drives(test)
    info = {"kind": "binary", "horizons": [30]}
    models, seeds = split_seeds({n: info for n in ("hazard_smart", "hazard_smart_seed1",
                                                    "binary_30d", "binary_30d_seed1")})
    out = seed_spread(test, D, models, seeds, [30])
    auc = {r["model"]: r["auc"] for r in out["rows"]}
    assert auc["hazard_smart"] == 1.0 and auc["hazard_smart_seed1"] == 0.5
    diffs = {d["seed_index"]: d["auc_diff"] for d in out["pair_differences"]}
    assert diffs == {0: 0.0, 1: -0.5}
    fam = {r["family"]: r for r in out["summary"]}
    assert fam["hazard_smart"]["replicates"] == 2


def test_on_stride_follows_the_drive_offset():
    serial = "Z1"
    off = int(stable_unit(serial, "stride") * 7)
    days = pd.date_range("2025-01-01", periods=21)
    frame = pd.DataFrame({"serial_number": serial, "date": days})
    hit = on_stride(frame, 7)
    assert hit.sum() == 3
    first = days[hit][0]
    assert ((first - pd.Timestamp("2000-01-01")).days + off) % 7 == 0


def test_weekly_alerts_use_only_stride_days():
    # one failing drive with daily rows in its last 30 days; alerts only off its stride days
    days = pd.date_range("2025-03-01", periods=30)
    serial = "F1"
    hit = on_stride(pd.DataFrame({"serial_number": serial, "date": days}), 7)
    rows = [(serial, d, 29 - i, 1, 0.1 if hit[i] else 0.99, "failing", "X", "V", 4)
            for i, d in enumerate(days)]
    # a non-failing drive, alerting on every row
    rows += [("Q1", d, 300, 0, 0.99, "healthy", "X", "V", 4) for d in days]
    rows += [("Q2", d, 300, 0, 0.1, "healthy", "X", "V", 4) for d in days]
    test = _frame(rows)
    val = _frame([(f"v{i}", "2023-01-01", 300, 0, i / 100, "healthy", "X", "V", 4)
                  for i in range(100)])
    D = Drives(test)
    models = {"m": {"kind": "binary", "horizons": [30]}}
    out = weekly_alerts(val, test, D, models, 30, [0.05], 7, [0.5], 5, 1, pair=("m", "m"))
    (b,) = out["budgets"]
    assert out["failing_drives_checked"] == 1
    assert b["share_failing_drives_alerted"] == 0.0      # its alerts fall between checks
    assert b["share_nonfailing_drives_alerted"] == 0.5
    # every score is above zero, so "any counter above zero" alerts every drive
    zero = out["any_critical_counter"]
    assert zero["share_nonfailing_drives_alerted"] == 1.0
    assert zero["share_failing_drives_alerted"] == 1.0


def test_windowed_alerts_count_drive_quarters():
    from evaluate import windowed_alerts
    rows = []
    # non-failing drive N1: alerts only in Q1; N2 never alerts; both seen in Q1 and Q2
    for d in pd.date_range("2025-01-01", "2025-06-30"):
        rows.append(("N1", d, 400, 0, 0.9 if d.month <= 3 else 0.1, "healthy", "X", "V", 4))
        rows.append(("N2", d, 400, 0, 0.1, "healthy", "X", "V", 4))
    # failing drive F1 fails on 2025-06-20, alerting every day of its last 30
    for d in pd.date_range("2025-04-01", "2025-06-20"):
        left = (pd.Timestamp("2025-06-20") - d).days
        rows.append(("F1", d, left, 1, 0.95 if left < 30 else 0.1, "failing", "X", "V", 4))
    test = _frame(rows)
    test["m__p30"] = test["s"]
    D = Drives(test)
    models = {"m": {"kind": "binary", "horizons": [30]}}
    out = windowed_alerts(test, D, models, 30, 7, [0.25], 5, 1, "Q", pair=("m", "m"))
    assert out["negative_units"] == 4          # N1 and N2 in Q1 and Q2; F1's Q2 is its failure
    assert out["positive_units"] == 1
    (r,) = out["matched"]
    assert r["nonfailing_share"] == 0.25       # only N1 in Q1 alerts
    assert r["share_failing_drives_alerted"] == 1.0


def test_validation_discrimination_ranks_known_status_snapshots():
    from evaluate import validation_discrimination
    rows = [("a", "2023-01-01", 10, 1, 0.9, "failing", "X", "V", 4),
            ("b", "2023-01-01", 300, 0, 0.1, "healthy", "X", "V", 4),
            ("c", "2023-01-01", 300, 0, 0.95, "healthy", "X", "V", 4),
            ("d", "2023-12-25", 6, 0, 0.5, "healthy", "X", "V", 4)]   # unknown at 30 days
    val = _frame(rows)
    out = validation_discrimination(val, {"m": {"kind": "binary", "horizons": [30]}}, [30])
    (r,) = out
    assert r["snapshots"] == 3 and r["positives"] == 1
    assert np.isclose(r["auc"], 0.5)

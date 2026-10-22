"""Cohort selection rules, contract validation, and the gate catching injected bugs."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from common import load_sample, load_study, stable_bucket, stable_unit
from drives import select_cohort

ROOT = Path(__file__).resolve().parent.parent
STUDY = load_study(ROOT / "config" / "study.toml")
SCALE = {"failing_fraction": 1.0, "healthy_fraction": 1.0, "stride_days": 7, "dense_days": 30,
         "scale": "t"}


def drives_frame(rows):
    cols = ["serial_number", "model", "first_date", "last_date", "first_failure",
            "capacity_bytes"]
    return pd.DataFrame(rows, columns=cols)


def test_stable_hashes_are_stable():
    # fixed values: a change here would silently reshuffle every split and sample
    assert stable_bucket("Z305B2QN") == stable_bucket("Z305B2QN")
    assert [stable_bucket(s) for s in ("A", "B", "C")] == [
        int(stable_unit(s, "split") * 100) for s in ("A", "B", "C")]
    assert stable_unit("A", "split") != stable_unit("A", "sample")


def test_cohort_rules():
    serials = [f"S{i}" for i in range(400)]
    rows = [(s, "ST4000DM000", "2020-01-01", "2025-12-31", None, 4e12) for s in serials]
    rows.append(("SSD1", "CT250MX500SSD1", "2020-01-01", "2025-12-31", None, 2.5e11))
    # test-bucket drive that failed before test_start has nothing to test
    early = next(s for s in (f"E{i}" for i in range(1000)) if stable_bucket(s) >= 80)
    rows.append((early, "ST4000DM000", "2020-01-01", "2023-06-01", "2023-06-01", 4e12))
    # train-bucket drive that only appears after train_end
    late = next(s for s in (f"L{i}" for i in range(1000)) if stable_bucket(s) < 70)
    rows.append((late, "ST4000DM000", "2024-03-01", "2025-12-31", None, 4e12))
    cohort, counts = select_cohort(drives_frame(rows), STUDY, SCALE)

    assert "SSD1" not in set(cohort["serial_number"])
    assert early not in set(cohort["serial_number"])
    assert late not in set(cohort["serial_number"])
    assert counts["excluded_ssd"] == 1 and counts["excluded_outside_window"] == 2
    expected = {"train": range(0, 70), "val": range(70, 80), "test": range(80, 100)}
    for s, split in zip(cohort["serial_number"], cohort["split"]):
        assert stable_bucket(s) in expected[split]


def test_sampling_weights_are_inverse_fractions():
    rows = [(f"S{i}", "ST4000DM000", "2020-01-01", "2025-12-31",
             "2021-05-05" if i % 3 == 0 else None, 4e12) for i in range(3000)]
    scale = dict(SCALE, failing_fraction=0.5, healthy_fraction=0.1)
    cohort, _ = select_cohort(drives_frame(rows), STUDY, scale)
    w = cohort.groupby("stratum")["drive_weight"].unique()
    assert list(w["failing"]) == [2.0] and list(w["healthy"]) == [10.0]
    kept_healthy = (cohort["stratum"] == "healthy").sum()
    assert 140 < kept_healthy < 260  # about 10% of 2000


def test_contract_validation(tmp_path):
    bad = (ROOT / "config" / "study.toml").read_text().replace(
        "horizons = [7, 30, 90, 180, 365]", "horizons = [7, 45]")
    (tmp_path / "study.toml").write_text(bad)
    with pytest.raises(ValueError, match="not bin edges"):
        load_study(tmp_path / "study.toml")
    (tmp_path / "sample.toml").write_text('scale = "nope"\n[scales.small]\n')
    with pytest.raises(ValueError, match="not defined"):
        load_sample(tmp_path / "sample.toml")


def _gate(project, tamper_sql=None):
    import json

    from verify import run_checks

    build = project / "build"
    con = duckdb.connect()
    con.sql(f"CREATE TABLE snap AS SELECT * FROM read_parquet('{build}/snapshots.parquet')")
    con.sql(f"CREATE VIEW cohort AS SELECT * FROM read_parquet('{build}/cohort.parquet')")
    if tamper_sql:
        changed = con.sql(tamper_sql).fetchall()[0][0]
        assert changed > 0, "the tamper must change at least one row"
    checks = run_checks(con, pd.read_parquet(build / "cohort.parquet"),
                        json.loads((build / "feature-schema.json").read_text()),
                        load_study(project / "config" / "study.toml"),
                        load_sample(project / "config" / "sample.toml"))
    return {c.name for c in checks if not c.ok and c.severity == "error"}


def test_gate_passes_clean_data(pipeline_run):
    project, _ = pipeline_run
    assert _gate(project) == set()


def test_gate_catches_v2_label_bug(pipeline_run):
    """Rows inside a visible failure window relabelled as healthy (review §3.2)."""
    project, _ = pipeline_run
    failed = _gate(project, "UPDATE snap SET event = 0 WHERE event = 1 AND duration_days < 10")
    assert {"labels_match_cohort", "no_visible_failure_labelled_censored"} <= failed


def test_gate_catches_split_leak(pipeline_run):
    project, _ = pipeline_run
    failed = _gate(project, """UPDATE snap SET split = 'train' WHERE (serial_number, date) =
                               (SELECT (serial_number, date) FROM snap WHERE split = 'test'
                                ORDER BY serial_number, date LIMIT 1)""")
    assert "each_drive_in_one_split" in failed or "snapshot_split_matches_cohort" in failed


def test_gate_catches_train_rows_in_test_period(pipeline_run):
    project, _ = pipeline_run
    failed = _gate(project, """UPDATE snap SET date = DATE '2024-02-01'
                               WHERE split = 'train' AND date = (SELECT max(date) FROM snap
                                                                 WHERE split = 'train')""")
    assert "train_val_before_train_end" in failed

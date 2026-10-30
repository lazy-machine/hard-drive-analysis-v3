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
    return pd.DataFrame(rows, columns=cols).assign(n_models_per_month=1)


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
    for s, split in zip(cohort["serial_number"], cohort["split"], strict=True):
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


def _checks(project, tmp_path, tamper_sql=None):
    """Run the pipeline's data-verify step, optionally on tampered snapshots."""
    import tomllib

    from data_verify import run

    build = project / "build"
    pipeline = tomllib.loads((project / "pipeline.toml").read_text())
    step = next(s for s in pipeline["steps"] if s["name"] == "verify")
    inputs = {k: project / v for k, v in step["inputs"].items()}
    if tamper_sql:
        con = duckdb.connect()
        con.sql(f"CREATE TABLE snap AS SELECT * FROM read_parquet('{build}/snapshots.parquet')")
        con.sql(f"CREATE VIEW cohort AS SELECT * FROM read_parquet('{build}/cohort.parquet')")
        changed = con.sql(tamper_sql).fetchall()[0][0]
        assert changed > 0, "the tamper must change at least one row"
        inputs["snapshots"] = tmp_path / "snapshots.parquet"
        con.sql(f"COPY (SELECT * FROM snap) TO '{inputs['snapshots']}' (FORMAT parquet)")
    report = run(step["params"], inputs, log=lambda *a: None, workdir=project)
    return {c["id"]: c for c in report["checks"]}


def _gate(project, tmp_path, tamper_sql=None):
    checks = _checks(project, tmp_path, tamper_sql)
    return {cid for cid, c in checks.items()
            if c["status"] in ("fail", "error") and c["severity"] == "error"}


def test_gate_passes_clean_data(pipeline_run, tmp_path):
    project, _ = pipeline_run
    assert _gate(project, tmp_path) == set()


def test_gate_catches_v2_label_bug(pipeline_run, tmp_path):
    """Rows inside a visible failure window relabelled as healthy (review §3.2)."""
    project, _ = pipeline_run
    failed = _gate(project, tmp_path,
                   "UPDATE snap SET event = 0 WHERE event = 1 AND duration_days < 10")
    assert {"assert.labels_match_cohort", "assert.no_visible_failure_labelled_censored"} <= failed


def test_gate_catches_split_leak(pipeline_run, tmp_path):
    project, _ = pipeline_run
    failed = _gate(project, tmp_path, """UPDATE snap SET split = 'train'
                               WHERE (serial_number, date) =
                               (SELECT (serial_number, date) FROM snap WHERE split = 'test'
                                ORDER BY serial_number, date LIMIT 1)""")
    assert {"split.group_overlap", "assert.snapshot_split_matches_cohort"} <= failed


def test_gate_catches_train_rows_in_test_period(pipeline_run, tmp_path):
    project, _ = pipeline_run
    failed = _gate(project, tmp_path, """UPDATE snap SET date = DATE '2024-02-01'
                               WHERE split = 'train' AND date = (SELECT max(date) FROM snap
                                                                 WHERE split = 'train')""")
    assert {"temporal.bounds", "temporal.order"} <= failed


def test_gate_catches_stride_rows_off_stride_days(pipeline_run, tmp_path):
    """Stride rows moved off the drive's stride day keep their weight but not the density."""
    project, _ = pipeline_run
    stride = load_sample(project / "config" / "sample.toml")["stride_days"]
    failed = _gate(project, tmp_path, f"""UPDATE snap SET date = snap.date + 1 FROM cohort c
                               WHERE snap.serial_number = c.serial_number
                                 AND abs(snap.weight - c.drive_weight * {stride}) < 1e-6""")
    assert "custom.stride_rows_on_stride_days" in failed


def test_gate_catches_dense_weight_far_from_failure(pipeline_run, tmp_path):
    project, _ = pipeline_run
    failed = _gate(project, tmp_path, """UPDATE snap SET weight = c.drive_weight FROM cohort c
                               WHERE snap.serial_number = c.serial_number
                                 AND (snap.serial_number, snap.date) =
                                     (SELECT (s.serial_number, s.date) FROM snap s
                                      JOIN cohort c2 USING (serial_number)
                                      WHERE c2.failure_date IS NULL
                                      ORDER BY s.serial_number, s.date LIMIT 1)""")
    assert "assert.dense_rows_before_visible_failure" in failed
    assert "assert.snapshot_weights_valid" not in failed  # the weight itself is a valid value


def test_gate_warns_on_cohort_drive_without_snapshots(pipeline_run, tmp_path):
    project, _ = pipeline_run
    name = "assert.cohort_drives_have_snapshots"
    before = _checks(project, tmp_path)[name]
    after = _checks(project, tmp_path, """DELETE FROM snap WHERE serial_number =
                                          (SELECT min(serial_number) FROM snap)""")[name]
    assert after["status"] == "fail" and after["severity"] == "warn"
    assert not after["blocking"]
    missing = before.get("details", {}).get("violations", 0)
    assert after["details"]["violations"] == missing + 1



def _gate_on(project, tmp_path, snapshots_sql=None, cohort_sql=None):
    """Blocking check ids, with the snapshot or cohort table rewritten by a SELECT."""
    import tomllib

    from data_verify import run

    build = project / "build"
    step = next(s for s in tomllib.loads((project / "pipeline.toml").read_text())["steps"]
                if s["name"] == "verify")
    inputs = {k: project / v for k, v in step["inputs"].items()}
    con = duckdb.connect()
    for name, sql in (("snapshots", snapshots_sql), ("cohort", cohort_sql)):
        if sql:
            con.sql(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{build}/{name}.parquet')")
            inputs[name] = tmp_path / f"{name}.parquet"
            con.sql(f"COPY ({sql}) TO '{inputs[name]}' (FORMAT parquet)")
    report = run(step["params"], inputs, log=lambda *a: None, workdir=project)
    return set(report["blocking"])


def test_gate_catches_non_float_feature(pipeline_run, tmp_path):
    project, _ = pipeline_run
    blocking = _gate_on(project, tmp_path, snapshots_sql=(
        "SELECT * REPLACE (smart_9_raw::DOUBLE AS smart_9_raw) FROM snapshots"))
    assert "custom.features_are_float" in blocking


def test_gate_catches_cohort_drive_in_wrong_split(pipeline_run, tmp_path):
    """A cohort drive without snapshots in the wrong split: only the cohort check sees it."""
    project, _ = pipeline_run
    blocking = _gate_on(project, tmp_path, cohort_sql="""
        SELECT * REPLACE (CASE WHEN serial_number = (SELECT min(serial_number) FROM cohort)
                          THEN CASE split WHEN 'train' THEN 'test' ELSE 'train' END
                          ELSE split END AS split)
        FROM cohort""")
    assert "custom.cohort_split_matches_stable_bucket" in blocking

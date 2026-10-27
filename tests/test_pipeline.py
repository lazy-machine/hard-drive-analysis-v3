"""End-to-end: the whole pipeline on the synthetic panel, then checks on its outputs."""

from __future__ import annotations

import json

import duckdb
import pandas as pd


def test_pipeline_runs_and_caches(pipeline_run):
    project, result = pipeline_run
    assert all(o.status == "ran" for o in result.outcomes.values())
    assert (project / "build" / "report" / "report.md").read_text().startswith("# Can SMART")

    from data_pipeline import config
    from data_pipeline.orchestrator import Orchestrator
    from data_pipeline.report import Reporter

    again = Orchestrator(config.load(project / "pipeline.toml"), Reporter(color=False)).run()
    assert again.ok
    assert {o.status for o in again.outcomes.values()} == {"cached"}


def test_gate_passed(pipeline_run):
    project, _ = pipeline_run
    report = json.loads((project / "build" / "verify-report.json").read_text())
    assert report["passed"]
    errors = [c for c in report["checks"] if not c["ok"] and c["severity"] == "error"]
    assert not errors


def test_cohort_excludes_ssd_and_normalizes_models(pipeline_run):
    project, _ = pipeline_run
    cohort = pd.read_parquet(project / "build" / "cohort.parquet")
    assert not cohort["model"].str.contains("SSD").any()
    assert not cohort["model"].str.contains("  ").any()
    summary = json.loads((project / "build" / "cohort-summary.json").read_text())
    assert summary["excluded_ssd"] > 0


def test_extract_dedups_and_cuts_at_failure(pipeline_run):
    project, _ = pipeline_run
    con = duckdb.connect()
    panel = f"read_parquet('{project}/build/panel/*/*.parquet', hive_partitioning = true)"
    dup = con.sql(f"SELECT count(*) - count(DISTINCT (serial_number, date)) FROM {panel}").fetchall()[0][0]
    assert dup == 0
    after = con.sql(f"""SELECT count(*) FROM {panel} p
        JOIN read_parquet('{project}/build/cohort.parquet') c USING (serial_number)
        WHERE c.failure_date IS NOT NULL AND p.date > c.failure_date""").fetchall()[0][0]
    assert after == 0
    # the VARCHAR-typed columns were cast, not dropped
    filled = con.sql(f"SELECT count(smart_18_raw) FROM {panel}").fetchall()[0][0]
    assert filled > 0


def test_train_failure_after_cutoff_is_censored_not_negative(pipeline_run):
    """The v2 bug (review §3.2): a train drive failing after the cutoff got label 0."""
    project, _ = pipeline_run
    con = duckdb.connect()
    rows = con.sql(f"""
        SELECT s.duration_days, s.event, s.date, c.failure_date
        FROM read_parquet('{project}/build/snapshots.parquet') s
        JOIN read_parquet('{project}/build/cohort.parquet') c USING (serial_number)
        WHERE s.split = 'train' AND c.failure_date > DATE '2023-12-31'""").df()
    assert len(rows) > 0, "synthetic data should contain such drives"
    assert (rows["event"] == 0).all()
    cutoff = pd.Timestamp("2023-12-31")
    expected = (cutoff - pd.to_datetime(rows["date"])).dt.days
    assert (rows["duration_days"] <= expected).all()


def test_trend_features_are_date_keyed(pipeline_run):
    """smart_5_raw_d30 = value now - earliest non-null value in the last 30 calendar days."""
    project, _ = pipeline_run
    con = duckdb.connect()
    panel = f"read_parquet('{project}/build/panel/*/*.parquet', hive_partitioning = true)"
    snap = con.sql(f"""SELECT serial_number, date, smart_5_raw, smart_5_raw_d30, window_days_30
        FROM read_parquet('{project}/build/snapshots.parquet')
        WHERE smart_5_raw > 0 ORDER BY serial_number, date LIMIT 40""").df()
    assert len(snap)
    for _, r in snap.iterrows():
        hist = con.sql(f"""SELECT date, smart_5_raw FROM {panel}
            WHERE serial_number = '{r.serial_number}' AND smart_5_raw IS NOT NULL
              AND date BETWEEN DATE '{r.date}' - INTERVAL 30 DAYS AND DATE '{r.date}'
            ORDER BY date""").df()
        assert abs(r.smart_5_raw_d30 - (r.smart_5_raw - hist["smart_5_raw"].iloc[0])) < 1e-3
        assert r.window_days_30 <= 30


def test_models_store_feature_names(pipeline_run):
    project, _ = pipeline_run
    from model import load_booster

    for name in ("hazard_smart", "hazard_nosmart", "binary_30d"):
        booster, meta = load_booster(project / "build" / "models" / f"{name}.txt",
                                     project / "build" / "models" / f"{name}.json")
        assert "date" not in meta["features"] and "date_days" not in meta["features"]
    _, meta = load_booster(project / "build" / "models" / "hazard_nosmart.txt",
                           project / "build" / "models" / "hazard_nosmart.json")
    assert not any(f.startswith("smart_") for f in meta["features"])


def test_smart_signal_is_found(pipeline_run):
    """The synthetic failures are announced by smart_5, so SMART must beat no-SMART."""
    project, _ = pipeline_run
    metrics = json.loads((project / "build" / "metrics.json").read_text())
    auc = {(r["model"], r["horizon"]): r["auc"] for r in metrics["discrimination"]}
    assert auc[("hazard_smart", 30)] > 0.9
    assert auc[("hazard_smart", 30)] > auc[("hazard_nosmart", 30)] + 0.1
    predictions = pd.read_parquet(project / "build" / "predictions.parquet")
    assert {"serial_number", "date"} <= set(predictions.columns)


def test_vendor_packed_raw_values_are_decoded(pipeline_run):
    """Seagate's 240 carries milliseconds above bit 32; only the hours (low 32 bits) stay."""
    project, _ = pipeline_run
    con = duckdb.connect()
    raw = con.sql(f"""SELECT max(smart_240_raw) FROM
        read_parquet('{project}/dataset/dataset.parquet')""").fetchall()[0][0]
    assert raw >= 2**32, "synthetic data should contain packed 240 values"
    panel = f"read_parquet('{project}/build/panel/*/*.parquet', hive_partitioning = true)"
    assert con.sql(f"SELECT max(smart_240_raw) FROM {panel}").fetchall()[0][0] < 2**32
    cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM {panel}").fetchall()]
    assert "smart_188_raw" not in cols and "smart_188_normalized" in cols


def test_unparseable_strings_are_counted(pipeline_run):
    project, _ = pipeline_run
    log = (project / "build" / "logs" / "extract.log").read_text()
    line = next(x for x in log.splitlines() if "strings that are not numbers" in x)
    assert "'smart_18_raw': 0" not in line

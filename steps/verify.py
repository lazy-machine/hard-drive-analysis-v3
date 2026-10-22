"""Pre-training verification gate.

Independent checks over the cohort and the snapshot table, all reading the same contract
(config/study.toml, config/sample.toml, the feature schema) as the steps that built the
data, so a check cannot silently drift from the code it guards. Every check runs and is
written to the report. The step then fails if any check has severity "error", which
stops the pipeline before training.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pandas as pd

from common import (
    ID_COLUMNS, LABEL_COLUMNS, LEAK_COLUMNS, connect, load_sample, load_study, q, scalar,
    stable_bucket,
)
from drives import assign_split
from panel import model_levels


@dataclass
class Check:
    name: str
    ok: bool
    severity: str  # error | warn
    detail: str


class GateFailed(Exception):
    pass


def run_checks(con, cohort: pd.DataFrame, schema: dict, study: dict, scale: dict) -> list[Check]:
    """All checks. `con` has views `snap` (snapshots) and `cohort`."""
    checks: list[Check] = []
    split = study["split"]

    def add(name, ok, detail, severity="error"):
        checks.append(Check(name, bool(ok), severity, detail))

    # -- cohort ------------------------------------------------------------------------
    add("cohort_serials_unique", cohort["serial_number"].is_unique,
        f"{len(cohort)} drives")
    expected = [assign_split(stable_bucket(s), split) for s in cohort["serial_number"]]
    wrong = int((cohort["split"] != pd.Series(expected, index=cohort.index)).sum())
    add("cohort_split_matches_stable_bucket", wrong == 0, f"{wrong} drives in the wrong split")
    frac = {"failing": scale["failing_fraction"], "healthy": scale["healthy_fraction"]}
    bad_w = int((cohort["drive_weight"] - cohort["stratum"].map(lambda s: 1 / frac[s])).abs()
                .gt(1e-9).sum())
    add("cohort_weights_match_sampling", bad_w == 0, f"{bad_w} drives with a wrong weight")

    # -- snapshot table shape ----------------------------------------------------------
    cols = [r[0] for r in con.sql("DESCRIBE SELECT * FROM snap").fetchall()]
    types = dict(con.sql("SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM snap)").fetchall())
    add("snapshot_columns_match_schema", cols == ID_COLUMNS + LABEL_COLUMNS + schema["features"],
        f"{len(cols)} columns")
    leaks = sorted(set(schema["features"]) & set(LEAK_COLUMNS))
    add("no_leak_columns_in_features", not leaks, f"leaking: {leaks}" if leaks else "none")
    non_float = [f for f in schema["features"] if types.get(f) != "FLOAT"]
    add("features_are_float", not non_float, f"non-FLOAT: {non_float[:5]}")
    add("date_is_date_type", types.get("date") == "DATE", f"date is {types.get('date')}")
    dup = scalar(con, "SELECT count(*) - count(DISTINCT (serial_number, date)) FROM snap")
    add("one_snapshot_per_drive_day", dup == 0, f"{dup} duplicates")

    # -- split integrity ---------------------------------------------------------------
    mixed = scalar(con, """SELECT count(*) FROM (SELECT serial_number FROM snap
                           GROUP BY serial_number HAVING count(DISTINCT split) > 1)""")
    add("each_drive_in_one_split", mixed == 0, f"{mixed} drives in several splits")
    mismatch = scalar(con, """SELECT count(*) FROM snap s LEFT JOIN cohort c USING (serial_number)
                              WHERE c.split IS NULL OR c.split <> s.split""")
    add("snapshot_split_matches_cohort", mismatch == 0, f"{mismatch} rows")
    late = scalar(con, f"""SELECT count(*) FROM snap WHERE split IN ('train', 'val')
                          AND date > DATE '{split['train_end']}'""")
    add("train_val_before_train_end", late == 0, f"{late} rows after {split['train_end']}")
    early = scalar(con, f"""SELECT count(*) FROM snap WHERE split = 'test'
                           AND date < DATE '{split['test_start']}'""")
    add("test_from_test_start", early == 0, f"{early} rows before {split['test_start']}")

    # -- labels, recomputed independently from the cohort (both directions) ------------
    after = scalar(con, """SELECT count(*) FROM snap s JOIN cohort c USING (serial_number)
                           WHERE c.failure_date IS NOT NULL AND s.date > c.failure_date""")
    add("no_snapshot_after_failure", after == 0, f"{after} rows")
    wrong_label = con.sql(f"""
        WITH expect AS (
            SELECT s.serial_number, s.date, s.duration_days, s.event,
                   CASE WHEN s.split = 'test' THEN c.last_date
                        ELSE least(c.last_date, DATE '{split['train_end']}') END AS censor,
                   c.failure_date
            FROM snap s JOIN cohort c USING (serial_number)
        ), e2 AS (
            SELECT *, (failure_date IS NOT NULL AND failure_date <= censor)::INT AS ev FROM expect
        )
        SELECT
            count(*) FILTER (WHERE event <> ev) AS event_wrong,
            count(*) FILTER (WHERE event = 1 AND duration_days <> date_diff('day', date, failure_date))
                AS failure_duration_wrong,
            count(*) FILTER (WHERE event = 0 AND duration_days <> date_diff('day', date, censor))
                AS censor_duration_wrong,
            count(*) FILTER (WHERE ev = 1 AND event = 0) AS missed_failures,
            count(*) FILTER (WHERE duration_days < 0) AS negative
        FROM e2""").fetchall()[0]
    names = ["event_wrong", "failure_duration_wrong", "censor_duration_wrong",
             "missed_failures", "negative"]
    add("labels_match_cohort", sum(wrong_label) == 0,
        ", ".join(f"{n}={v}" for n, v in zip(names, wrong_label)))
    leak = scalar(con, f"""SELECT count(*) FROM snap s JOIN cohort c USING (serial_number)
                          WHERE s.split IN ('train', 'val') AND s.event = 1
                            AND c.failure_date > DATE '{split['train_end']}'""")
    add("train_labels_do_not_see_test_period", leak == 0, f"{leak} rows")
    horizon = study["label"]["binary_horizon"]
    in_window_zero = scalar(con, f"""SELECT count(*) FROM snap s JOIN cohort c USING (serial_number)
        WHERE s.event = 0 AND c.failure_date IS NOT NULL
          AND date_diff('day', s.date, c.failure_date) < {horizon}
          AND (s.split = 'test' OR c.failure_date <= DATE '{split['train_end']}')""")
    add("no_visible_failure_labelled_censored", in_window_zero == 0,
        f"{in_window_zero} rows within {horizon} days of a visible failure have event = 0")

    # -- weights -----------------------------------------------------------------------
    stride = scale["stride_days"]
    bad_sw = scalar(con, f"""SELECT count(*) FROM snap s JOIN cohort c USING (serial_number)
        WHERE NOT (abs(s.weight - c.drive_weight) < 1e-6
                   OR abs(s.weight - c.drive_weight * {stride}) < 1e-6)""")
    add("snapshot_weights_valid", bad_sw == 0, f"{bad_sw} rows")

    # -- events and features -----------------------------------------------------------
    for s in ("train", "val", "test"):
        n_ev = scalar(con, f"SELECT count(DISTINCT serial_number) FROM snap WHERE split = '{s}' AND event = 1")
        add(f"failures_present_{s}", n_ev > 0, f"{n_ev} failing drives")
        add(f"enough_failures_{s}", n_ev >= 30, f"{n_ev} failing drives (< 30 is noisy)", "warn")
    fill = con.sql("SELECT " + ", ".join(f'count("{f}")::DOUBLE / count(*)' for f in schema["features"])
                   + " FROM snap WHERE split = 'train'").fetchall()[0]
    empty = [f for f, v in zip(schema["features"], fill) if v == 0]
    sparse = [f for f, v in zip(schema["features"], fill) if 0 < v < 0.01]
    add("no_empty_features", not empty, f"empty in train: {empty}", "warn")
    add("few_sparse_features", len(sparse) <= len(schema["features"]) // 4,
        f"< 1% filled in train: {sparse}", "warn")
    levels = model_levels(cohort, study["features"]["top_models"])
    add("model_levels_from_train_only", schema["categorical"]["model_code"] == levels + ["other"],
        f"{len(levels)} levels")
    return checks


def verify(ctx):
    study = load_study(ctx.inputs["study"])
    scale = load_sample(ctx.inputs["sample"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    cohort = pd.read_parquet(ctx.inputs["cohort"])
    con = connect(ctx.workdir, ctx.name)
    con.sql(f"CREATE VIEW snap AS SELECT * FROM read_parquet({q(ctx.inputs['snapshots'])})")
    con.sql(f"CREATE VIEW cohort AS SELECT * FROM read_parquet({q(ctx.inputs['cohort'])})")
    checks = run_checks(con, cohort, schema, study, scale)

    errors = [c for c in checks if not c.ok and c.severity == "error"]
    warnings = [c for c in checks if not c.ok and c.severity == "warn"]
    report = {"passed": not errors, "checks": [asdict(c) for c in checks]}
    ctx.outputs["report"].write_text(json.dumps(report, indent=2) + "\n")
    for c in checks:
        ctx.log(("PASS" if c.ok else c.severity.upper()).ljust(5), c.name, "-", c.detail)
    if errors:
        raise GateFailed("verification failed: " + "; ".join(f"{c.name} ({c.detail})" for c in errors))
    return {"checks": len(checks), "warnings": len(warnings)}

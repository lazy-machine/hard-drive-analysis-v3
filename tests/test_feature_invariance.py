"""Snapshot features must not look at rows after the snapshot date.

extract + snapshots run twice with the same cohort: once on the synthetic panel, once on
the same panel with every row after a cutoff removed. Snapshots on or before the cutoff
must have identical feature values in both runs.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

CUTOFF = "2024-03-15"  # after test_start, so test drives and their trend history are covered


class Ctx:
    """The parts of the data-pipeline step context that extract and snapshots use."""

    def __init__(self, workdir: Path, name: str, inputs: dict, outputs: dict, params=None):
        self.workdir, self.name = workdir, name
        self.inputs, self.outputs, self.params = inputs, outputs, params or {}

    def log(self, *parts):
        pass


def _build(project: Path, panel: Path, work: Path) -> Path:
    from panel import extract, snapshots

    cohort = project / "build" / "cohort.parquet"
    study, sample = project / "config" / "study.toml", project / "config" / "sample.toml"
    panel_dir = work / "build" / "panel"
    extract(Ctx(work, "extract", {"panel": panel, "cohort": cohort, "study": study},
                {"panel_dir": panel_dir}, {"batches": 3, "chunk_months": 1}))
    snaps = work / "build" / "snapshots.parquet"
    snapshots(Ctx(work, "snapshots",
                  {"panel_dir": panel_dir, "cohort": cohort, "study": study, "sample": sample},
                  {"snapshots": snaps, "schema": work / "build" / "feature-schema.json"}))
    return snaps


def test_features_do_not_see_the_future(pipeline_run, tmp_path):
    import json

    project, _ = pipeline_run
    full_panel = project / "dataset" / "dataset.parquet"
    cut_panel = tmp_path / "cut.parquet"
    con = duckdb.connect()
    con.sql(f"""COPY (SELECT * FROM read_parquet('{full_panel}') WHERE date <= DATE '{CUTOFF}')
                TO '{cut_panel}' (FORMAT PARQUET)""")

    full = _build(project, full_panel, tmp_path / "full")
    cut = _build(project, cut_panel, tmp_path / "cut")
    schema_path = tmp_path / "full" / "build" / "feature-schema.json"
    features = json.loads(schema_path.read_text())["features"]

    both = (f"read_parquet('{cut}') a JOIN read_parquet('{full}') b USING (serial_number, date) "
            f"WHERE date <= DATE '{CUTOFF}'")
    n_cut = con.sql(f"SELECT count(*) FROM read_parquet('{cut}') "
                    f"WHERE date <= DATE '{CUTOFF}'").fetchall()[0][0]
    n_both, n_test = con.sql(f"SELECT count(*), count(*) FILTER (WHERE a.split = 'test') "
                             f"FROM {both}").fetchall()[0]
    assert n_both == n_cut > 1000, "row selection depends on the cohort only, not on later rows"
    assert n_test > 0, "the comparison must cover test snapshots after test_start"
    diffs = con.sql("SELECT " + ", ".join(
        f'count(*) FILTER (WHERE a."{f}" IS DISTINCT FROM b."{f}")' for f in features)
        + f" FROM {both}").fetchall()[0]
    changed = {f: n for f, n in zip(features, diffs, strict=True) if n}
    assert not changed, f"features changed when later rows were removed: {changed}"

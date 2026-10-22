"""Fixtures: a synthetic project directory, and one end-to-end pipeline run over it."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TEST_SAMPLE = """scale = "test"
[scales.test]
failing_fraction = 1.0
healthy_fraction = 0.5
stride_days = 3
dense_days = 30
"""


@pytest.fixture(scope="session")
def project(tmp_path_factory) -> Path:
    """A copy of the project (config + pipeline) pointing at a synthetic panel."""
    import sys

    sys.path.insert(0, str(ROOT / "steps"))
    sys.path.insert(0, str(ROOT / "tests"))
    from common import load_study, smart_columns
    from synth import make_panel

    work = tmp_path_factory.mktemp("hda")
    shutil.copytree(ROOT / "config", work / "config")
    (work / "steps").symlink_to(ROOT / "steps")
    (work / "config" / "sample.toml").write_text(TEST_SAMPLE)
    study = (work / "config" / "study.toml").read_text()
    study = re.sub(r"bootstrap_rounds = \d+", "bootstrap_rounds = 30", study)
    study = re.sub(r"top_models = \d+", "top_models = 3", study)
    (work / "config" / "study.toml").write_text(study)
    pipeline = (ROOT / "pipeline.toml").read_text()
    pipeline = pipeline.replace("batches = 8", "batches = 3")
    pipeline = pipeline.replace("min_child_samples = 200", "min_child_samples = 20")
    (work / "pipeline.toml").write_text(pipeline)

    cols = smart_columns(load_study(work / "config" / "study.toml"))
    (work / "dataset").mkdir()
    make_panel(cols).to_parquet(work / "dataset" / "dataset.parquet", index=False)
    return work


@pytest.fixture(scope="session")
def pipeline_run(project):
    """Run the whole pipeline once on the synthetic project."""
    from data_pipeline import config
    from data_pipeline.orchestrator import Orchestrator
    from data_pipeline.report import Reporter

    os.environ.setdefault("HDA_THREADS", "2")
    result = Orchestrator(config.load(project / "pipeline.toml"),
                          Reporter(color=False)).run()
    failed = {n: o for n, o in result.outcomes.items() if o.status not in ("ran", "cached")}
    assert result.ok and not failed, {n: (o.detail, o.output[-3000:]) for n, o in failed.items()}
    return project, result

"""Score validation and test snapshots with every trained model and the rule baseline.

Models are discovered from the step's inputs (`model_<name>` + `meta_<name>`), so the
list lives only in pipeline.toml.

Output columns per model, named `<model>__<quantity>`:
- hazard models: p<H> (P(fail within H days)) for each horizon, plus median_days,
  q10_days, q90_days (days until the failure probability reaches 50/10/90%; inf = beyond
  the last bin edge) and rmst_days (expected days alive within the last bin edge);
- binary models: p<H> for their single horizon;
- rule_counters: a score (no probabilities), log-sum of the critical SMART counters.

A hazard model trained with `recalibrate_recent` also appears as `<model>_recent`: the
same trees with the calibration refitted on the last validation year before train_end.

Models from steps/engines.py (XGBoost, CatBoost, PyTorch) carry `engine` in their
metadata and are scored through engines.load; LightGBM models have no `engine` key.
params.ensembles = {name = [model, ...]} adds hazard models whose per-bin hazard is the
mean of the members' calibrated hazards.
`critical_nonzero` flags snapshots where any critical counter is above zero (evaluate
uses it for the silent-failure slice).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import engines
from common import Progress, load_snapshots, load_study
from model import load_booster, raw_hazard_logits
from survival import (
    apply_platt, failure_probability, hazards_to_survival, life_quantile, restricted_mean_life,
)

RULE = "rule_counters"
CHUNK = 200_000


def calibrated_hazards(z: np.ndarray, calibration) -> np.ndarray:
    """Hazard per bin from raw logits per bin and a calibration, shape (n, bins)."""
    return np.column_stack([apply_platt(z[:, k], c) for k, c in enumerate(calibration)])


def _hazard_columns(h: np.ndarray, edges: list[int], horizons: list[int],
                    name: str) -> dict[str, np.ndarray]:
    """Output columns of a hazard model from its calibrated hazards per bin."""
    S = hazards_to_survival(h)
    cols = {f"{name}__p{H}": failure_probability(S, edges, H) for H in horizons}
    cols[f"{name}__median_days"] = life_quantile(S, edges, 0.5)
    cols[f"{name}__q10_days"] = life_quantile(S, edges, 0.1)
    cols[f"{name}__q90_days"] = life_quantile(S, edges, 0.9)
    cols[f"{name}__rmst_days"] = restricted_mean_life(S, edges)
    return cols


def rule_score(X: np.ndarray) -> np.ndarray:
    """Sum of log1p(counter) over the critical counters; missing counts as zero."""
    return np.log1p(np.clip(np.nan_to_num(X, nan=0.0), 0, None)).sum(axis=1)


def predict(ctx):
    log = Progress(ctx)
    study = load_study(ctx.inputs["study"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    edges = study["label"]["bin_edges"]
    horizons = study["label"]["horizons"]
    names = sorted(k.removeprefix("model_") for k in ctx.inputs if k.startswith("model_"))

    meta, X = load_snapshots(ctx.inputs["snapshots"], ["val", "test"], schema["features"])
    log(f"{len(meta)} snapshots, models: {', '.join(names)}")
    position = {f: j for j, f in enumerate(schema["features"])}
    out = {c: meta[c].to_numpy() for c in meta.columns}

    ensembles = ctx.params.get("ensembles", {})
    members = {m for ms in ensembles.values() for m in ms}
    unknown = sorted(members - set(names))
    if unknown:
        raise ValueError(f"ensemble members {unknown} are not among the models {names}")
    hazards = {}
    for name in names:
        info = json.loads(ctx.inputs[f"meta_{name}"].read_text())
        if "engine" in info:
            scorer = engines.load(ctx.inputs[f"model_{name}"], info)
            if info.get("needs_panel"):
                scorer.windows = engines.PanelWindows.build(
                    ctx.inputs["panel_dir"], ctx.inputs["snapshots"], ["val", "test"], study,
                    scorer.scaling, scorer.device, log)
            logits = scorer.hazard_logits
        else:
            booster, info = load_booster(ctx.inputs[f"model_{name}"], ctx.inputs[f"meta_{name}"])

            def logits(Xm, booster=booster):
                return raw_hazard_logits(booster, Xm, edges, CHUNK)
        Xm = X[:, [position[f] for f in info["features"]]]
        if info["kind"] == "hazard":
            if info["bin_edges"] != edges:
                raise ValueError(f"{name} was trained with bins {info['bin_edges']}, "
                                 f"study has {edges}")
            z = logits(Xm)                                     # shared by both calibrations
            h = calibrated_hazards(z, info["calibration"])
            out.update(_hazard_columns(h, edges, horizons, name))
            if name in members:
                hazards[name] = h
            if "calibration_recent" in info:
                out.update(_hazard_columns(calibrated_hazards(z, info["calibration_recent"]),
                                           edges, horizons, f"{name}_recent"))
        else:
            H = info["binary_horizon"]
            z = np.concatenate([booster.predict(Xm[lo:lo + CHUNK], raw_score=True)
                                for lo in range(0, len(Xm), CHUNK)])
            out[f"{name}__p{H}"] = apply_platt(z, info["calibration"][0])
        log(f"scored {name}")
    for name, ms in sorted(ensembles.items()):
        out.update(_hazard_columns(np.mean([hazards[m] for m in ms], axis=0), edges, horizons,
                                   name))
        log(f"ensemble {name}: mean hazard of {', '.join(ms)}")

    counters = study["features"]["critical_counters"]
    Xc = X[:, [position[c] for c in counters]]
    out[f"{RULE}__score"] = rule_score(Xc)
    out["critical_nonzero"] = (np.nan_to_num(Xc, nan=0.0) > 0).any(axis=1)

    table = pa.Table.from_pandas(pd.DataFrame(out), preserve_index=False)
    pq.write_table(table, ctx.outputs["predictions"], compression="zstd")
    return {"rows": len(meta), "models": len(names) + len(ensembles) + 1}

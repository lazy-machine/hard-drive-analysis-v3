"""Score validation and test snapshots with every trained model and the rule baseline.

Models are discovered from the step's inputs (`model_<name>` + `meta_<name>`), so the
list lives only in pipeline.toml.

Output columns per model, named `<model>__<quantity>`:
- hazard models: p<H> (P(fail within H days)) for each horizon, plus median_days,
  q10_days, q90_days (days until the failure probability reaches 50/10/90%; inf = beyond
  the last bin edge) and rmst_days (expected days alive within the last bin edge);
- binary models: p<H> for their single horizon;
- rule_counters: a score (no probabilities), log-sum of the critical SMART counters.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from common import Progress, load_snapshots, load_study
from model import load_booster
from survival import failure_probability, hazards_to_survival, life_quantile, restricted_mean_life

RULE = "rule_counters"
CHUNK = 200_000


def _hazard_columns(booster, X: np.ndarray, edges: list[int], horizons: list[int],
                    name: str) -> dict[str, np.ndarray]:
    n = X.shape[0]
    K = len(edges) - 1
    h = np.empty((n, K))
    for lo in range(0, n, CHUNK):
        part = X[lo:lo + CHUNK]
        for k in range(K):
            with_bin = np.hstack([part, np.full((part.shape[0], 1), edges[k], np.float32)])
            h[lo:lo + CHUNK, k] = booster.predict(with_bin)
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

    for name in names:
        booster, info = load_booster(ctx.inputs[f"model_{name}"], ctx.inputs[f"meta_{name}"])
        Xm = X[:, [position[f] for f in info["features"]]]
        if info["kind"] == "hazard":
            if info["bin_edges"] != edges:
                raise ValueError(f"{name} was trained with bins {info['bin_edges']}, "
                                 f"study has {edges}")
            out.update(_hazard_columns(booster, Xm, edges, horizons, name))
        else:
            H = info["binary_horizon"]
            out[f"{name}__p{H}"] = np.concatenate(
                [booster.predict(Xm[lo:lo + CHUNK]) for lo in range(0, len(Xm), CHUNK)])
        log(f"scored {name}")

    counters = study["features"]["critical_counters"]
    out[f"{RULE}__score"] = rule_score(X[:, [position[c] for c in counters]])

    table = pa.Table.from_pandas(pd.DataFrame(out), preserve_index=False)
    pq.write_table(table, ctx.outputs["predictions"], compression="zstd")
    return {"rows": len(meta), "models": len(names) + 1}

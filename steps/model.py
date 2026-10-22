"""Model training: discrete-time hazard models and the fixed-horizon baseline classifier.

One pipeline step per model, all calling `train` with different params:

- kind = "hazard": LightGBM on person-period rows (snapshot features + bin start). It
  predicts P(fail in bin | alive at bin start), so each snapshot gets a survival curve.
- kind = "binary": the v2-style "fails within H days?" classifier, trained only on
  snapshots whose status at H is known (a censored snapshot is not a negative).

Early stopping uses the validation *drives* (drive-grouped), never the test split.
"""

from __future__ import annotations

import json
import os

import lightgbm as lgb
import numpy as np

from common import Progress, available_memory, load_snapshots, load_study, write_json
from survival import ExpandedSequence, expand, known_status

BASE_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}


def model_features(schema: dict, feature_set: str) -> list[str]:
    if feature_set == "all":
        return list(schema["features"])
    if feature_set in schema["groups"]:
        return list(schema["groups"][feature_set])
    raise ValueError(f"unknown feature set '{feature_set}' (all, {', '.join(schema['groups'])})")


def _check_memory(n_rows: int, n_features: int, X_bytes: int, log) -> None:
    """Fail early with a clear message instead of being OOM-killed mid-training."""
    # LightGBM bins every value into one byte per feature (row-wise histograms add a
    # little more); the snapshot matrices stay in memory while the Dataset is built.
    need = X_bytes + n_rows * (n_features + 1) * 2
    avail = available_memory()
    log(f"memory estimate {need / 2**30:.1f} GiB, available {avail / 2**30:.1f} GiB")
    if need > 0.9 * avail:
        raise MemoryError(
            f"training needs about {need / 2**30:.1f} GiB but only {avail / 2**30:.1f} GiB "
            "is available. Lower healthy_fraction or raise stride_days in config/sample.toml.")


def _datasets(kind, meta_tr, X_tr, meta_va, X_va, features, categorical, study):
    edges = study["label"]["bin_edges"]
    names = list(features)
    if kind == "hazard":
        names.append("bin_start")
        built = []
        for meta, X in ((meta_tr, X_tr), (meta_va, X_va)):
            idx, bins, y, w = expand(meta["duration_days"].to_numpy(), meta["event"].to_numpy(),
                                     meta["weight"].to_numpy(), edges)
            start = np.asarray(edges)[bins]
            built.append((ExpandedSequence(X, idx, start), y, w))
    elif kind == "binary":
        horizon = study["label"]["binary_horizon"]
        built = []
        for meta, X in ((meta_tr, X_tr), (meta_va, X_va)):
            status = known_status(meta["duration_days"].to_numpy(), meta["event"].to_numpy(),
                                  horizon)
            keep = status >= 0
            built.append((X[keep], status[keep], meta["weight"].to_numpy()[keep]))
    else:
        raise ValueError(f"unknown model kind '{kind}'")

    (seq_tr, y_tr, w_tr), (seq_va, y_va, w_va) = built
    train_ds = lgb.Dataset(seq_tr, label=y_tr, weight=w_tr, feature_name=names,
                           categorical_feature=categorical, free_raw_data=True)
    valid_ds = lgb.Dataset(seq_va, label=y_va, weight=w_va, reference=train_ds,
                           free_raw_data=True)
    stats = {"train_rows": int(len(y_tr)), "train_events": int(y_tr.sum()),
             "val_rows": int(len(y_va)), "val_events": int(y_va.sum())}
    return train_ds, valid_ds, names, stats


def train(ctx):
    log = Progress(ctx)
    p = ctx.params
    study = load_study(ctx.inputs["study"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    features = model_features(schema, p["features"])
    categorical = [f for f in features if f in schema["categorical"]]

    meta_tr, X_tr = load_snapshots(ctx.inputs["snapshots"], ["train"], features)
    meta_va, X_va = load_snapshots(ctx.inputs["snapshots"], ["val"], features)
    log(f"{p['kind']} / {p['features']}: {len(features)} features, "
        f"{len(meta_tr)} train and {len(meta_va)} val snapshots")
    if meta_tr["event"].sum() == 0 or meta_va["event"].sum() == 0:
        raise ValueError("train and val need at least one failure each")

    n_bins = len(study["label"]["bin_edges"]) - 1 if p["kind"] == "hazard" else 1
    _check_memory((len(meta_tr) + len(meta_va)) * n_bins, len(features),
                  X_tr.nbytes + X_va.nbytes, log)
    train_ds, valid_ds, names, stats = _datasets(
        p["kind"], meta_tr, X_tr, meta_va, X_va, features, categorical, study)
    log(stats)

    params = {**BASE_PARAMS, **p["lgbm"], "seed": p["seed"],
              "num_threads": int(os.environ.get("HDA_THREADS", 0))}
    history: dict = {}
    booster = lgb.train(
        params, train_ds, num_boost_round=p["num_boost_round"], valid_sets=[valid_ds],
        valid_names=["val"],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False),
                   lgb.record_evaluation(history)])
    best = booster.best_iteration or p["num_boost_round"]
    val_loss = history["val"]["binary_logloss"][best - 1]
    log(f"best iteration {best}, val logloss {val_loss:.6g}")

    booster.save_model(str(ctx.outputs["model"]), num_iteration=best)
    gain = booster.feature_importance("gain", iteration=best)
    write_json(ctx.outputs["meta"], {
        "name": ctx.name, "kind": p["kind"], "feature_set": p["features"],
        "features": features, "model_features": names, "categorical": categorical,
        "bin_edges": study["label"]["bin_edges"],
        "binary_horizon": study["label"]["binary_horizon"],
        "params": params, "best_iteration": best, "val_logloss": val_loss, **stats,
        "importance_gain": {n: float(g) for n, g in sorted(
            zip(names, gain), key=lambda t: -t[1])},
    })
    return {"best_iter": best, "val_logloss": val_loss, **stats}


def load_booster(model_path, meta_path) -> tuple[lgb.Booster, dict]:
    """Load a model and check its stored feature names against its metadata."""
    booster = lgb.Booster(model_file=str(model_path))
    meta = json.loads(meta_path.read_text())
    if booster.feature_name() != meta["model_features"]:
        raise ValueError(f"{model_path.name}: model features {booster.feature_name()} do not "
                         f"match its metadata {meta['model_features']}")
    return booster, meta

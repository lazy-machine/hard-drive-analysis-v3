"""Model training: discrete-time hazard models and the fixed-horizon baseline classifier.

One pipeline step per model, all calling `train` with different params:

- kind = "hazard": LightGBM on person-period rows (snapshot features + bin start). It
  predicts P(fail in bin | alive at bin start), so each snapshot gets a survival curve.
- kind = "binary": the v2-style "fails within H days?" classifier, trained only on
  snapshots whose status at H is known (a censored snapshot is not a negative).

Weights: training uses inverse-probability weights raised to `weight_power`. Full weights
(power 1) make the effective sample tiny: healthy drive-days weigh ~70x a failure row at
the small scale, and the model barely moves off the base rate before early stopping.
Tempering them improves ranking. The probabilities are then put back on the real scale by
a Platt fit per hazard bin on the validation drives, using the *true* weights. That fit
also fixes the over-confidence that compounding hazards produce at long horizons.

Early stopping and calibration use the validation *drives* (drive-grouped), never test.
"""

from __future__ import annotations

import json
import os

import lightgbm as lgb
import numpy as np

from common import Progress, available_memory, load_snapshots, load_study, write_json
from survival import ExpandedSequence, expand, fit_platt, known_status

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


def _rows(kind, meta, X, study):
    """Training rows for one split: (data, label, true weight, bin per row or None)."""
    edges = study["label"]["bin_edges"]
    d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    if kind == "hazard":
        idx, bins, y, w_rows = expand(d, e, w, edges)
        return ExpandedSequence(X, idx, np.asarray(edges)[bins]), y, w_rows, bins
    if kind == "binary":
        status = known_status(d, e, study["label"]["binary_horizon"])
        keep = status >= 0
        return X[keep], status[keep], w[keep], None
    raise ValueError(f"unknown model kind '{kind}'")


def raw_hazard_logits(booster: lgb.Booster, X: np.ndarray, edges: list[int],
                      chunk: int = 200_000) -> np.ndarray:
    """Uncalibrated logit of the hazard in every bin, shape (n, bins)."""
    K = len(edges) - 1
    z = np.empty((X.shape[0], K))
    for lo in range(0, X.shape[0], chunk):
        part = X[lo:lo + chunk]
        for k in range(K):
            with_bin = np.hstack([part, np.full((part.shape[0], 1), edges[k], np.float32)])
            z[lo:lo + chunk, k] = booster.predict(with_bin, raw_score=True)
    return z


def calibrate(booster, kind, meta_va, X_va, study) -> list[list[float]]:
    """Platt coefficients per hazard bin (or one pair for binary), fitted on validation
    drives with the true inverse-probability weights."""
    data, y, w, bins = _rows(kind, meta_va, X_va, study)
    if kind == "binary":
        return [fit_platt(booster.predict(data, raw_score=True), y, w)]
    z = raw_hazard_logits(booster, X_va, study["label"]["bin_edges"])
    coefs = []
    for k in range(z.shape[1]):
        m = bins == k
        if y[m].sum() == 0:
            raise ValueError(f"no validation failure in bin {k}: cannot calibrate it")
        coefs.append(fit_platt(z[data.idx[m], k], y[m], w[m]))
    return coefs


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
    names = features + (["bin_start"] if p["kind"] == "hazard" else [])
    power = p.get("weight_power", 1.0)
    data_tr, y_tr, w_tr, _ = _rows(p["kind"], meta_tr, X_tr, study)
    data_va, y_va, w_va, _ = _rows(p["kind"], meta_va, X_va, study)
    train_ds = lgb.Dataset(data_tr, label=y_tr, weight=w_tr ** power, feature_name=names,
                           categorical_feature=categorical, free_raw_data=True)
    valid_ds = lgb.Dataset(data_va, label=y_va, weight=w_va ** power, reference=train_ds,
                           free_raw_data=True)
    stats = {"train_rows": int(len(y_tr)), "train_events": int(y_tr.sum()),
             "val_rows": int(len(y_va)), "val_events": int(y_va.sum())}
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
    booster = lgb.Booster(model_file=str(ctx.outputs["model"]))  # exactly what predict sees
    calibration = calibrate(booster, p["kind"], meta_va, X_va, study)
    log(f"calibration (a, b) per bin: {[[round(a, 3), round(b, 3)] for a, b in calibration]}")
    gain = booster.feature_importance("gain", iteration=best)
    write_json(ctx.outputs["meta"], {
        "name": ctx.name, "kind": p["kind"], "feature_set": p["features"],
        "features": features, "model_features": names, "categorical": categorical,
        "bin_edges": study["label"]["bin_edges"],
        "binary_horizon": study["label"]["binary_horizon"],
        "params": params, "weight_power": power, "calibration": calibration,
        "best_iteration": best, "val_logloss": val_loss, **stats,
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

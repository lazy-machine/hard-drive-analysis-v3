"""XGBoost hazard model: the baseline's person-period setup on a different boosting engine.

One binary classifier over (snapshot, bin) rows with the bin start as a feature. Differences
from the LightGBM baseline: XGBoost hist trees grown leaf-wise, native missing values (NaN
goes to the learned default side), native categorical splits on model_code and vendor_code,
and a QuantileDMatrix built from a batch iterator, so the 6 GiB expanded float matrix never
exists (only its 8-bit histogram bins do). Healthy rows are subsampled when the expanded set
exceeds ROW_CAP, with the weight of each kept row divided by its keep probability.
"""

from __future__ import annotations

import os
import time

import numpy as np
import xgboost as xgb

from survival import expand

THREADS = int(os.environ.get("HDA_THREADS", 0))
PARAMS = {
    "objective": "binary:logistic", "eval_metric": "logloss", "tree_method": "hist",
    "grow_policy": "lossguide", "max_depth": 0, "max_leaves": 48, "max_bin": 256,
    "learning_rate": 0.05, "min_child_weight": 1.0, "reg_lambda": 10.0, "reg_alpha": 0.0,
    "subsample": 0.8, "colsample_bytree": 0.8, "max_cat_to_onehot": 4, "max_cat_threshold": 32,
    "seed": 42, "verbosity": 1, **({"nthread": THREADS} if THREADS else {}),
}
WEIGHT_POWER = 0.5
ROUNDS = 5000
PATIENCE = 100
ROW_CAP = 16_000_000        # expanded training rows kept; healthy rows beyond this are thinned
STOP_CAP = 3_000_000
MARGIN = 30                 # seconds kept free before the deadline for the final save


def _expanded(part, edges, cap, seed):
    d, e, w = (part.meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, weight = expand(d, e, w, edges)
    weight = weight ** WEIGHT_POWER
    neg = y == 0
    n_neg = int(neg.sum())
    if idx.size > cap and n_neg:
        p = max((cap - (idx.size - n_neg)) / n_neg, 0.05)
        keep = ~neg | (np.random.default_rng(seed).random(idx.size) < p)
        weight = np.where(neg, weight / p, weight)
        idx, bins, y, weight = idx[keep], bins[keep], y[keep], weight[keep]
        print(f"thinned healthy rows to {p:.3f}: {idx.size} rows kept", flush=True)
    return idx, np.asarray(edges, dtype=np.float32)[bins], y, weight.astype(np.float32)


class Batches(xgb.DataIter):
    """Feeds expanded rows X[idx] + bin start to XGBoost a slice at a time."""

    def __init__(self, X, idx, start, y, w, names, types, size=1 << 21):
        super().__init__()
        self.X, self.idx, self.start, self.y, self.w, self.size = X, idx, start, y, w, size
        self.names, self.types, self.pos = names, types, 0

    def next(self, input_data):
        if self.pos >= self.idx.size:
            return False
        s = slice(self.pos, self.pos + self.size)
        rows = np.hstack([self.X[self.idx[s]], self.start[s, None]])
        input_data(data=rows, label=self.y[s], weight=self.w[s], feature_names=self.names,
                   feature_types=self.types)
        self.pos += self.size
        return True

    def reset(self):
        self.pos = 0


def _types(features, categorical):
    return ["c" if f in categorical else "q" for f in features] + ["q"]


def prepare(data, model_dir):
    names = data.features + ["bin_start"]
    types = _types(data.features, data.categorical)
    kw = {"enable_categorical": True, "max_bin": PARAMS["max_bin"], "missing": np.nan}
    if THREADS:
        kw["nthread"] = THREADS
    out = []
    for part, cap, seed, ref in ((data.train, ROW_CAP, 1, None), (data.stop, STOP_CAP, 2, "train")):
        idx, start, y, w = _expanded(part, data.bin_edges, cap, seed)
        it = Batches(np.array(part.X), idx, start, y, w, names, types)
        out.append(xgb.QuantileDMatrix(it, ref=out[0] if ref else None, **kw))
        print(f"{'stop' if ref else 'train'} matrix: {idx.size} rows", flush=True)
    return out


class Deadline(xgb.callback.TrainingCallback):
    def __init__(self, deadline):
        self.deadline, self.last, self.slowest = deadline, time.time(), 0.0

    def after_iteration(self, model, epoch, evals_log):
        now = time.time()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now + 2 * self.slowest > self.deadline - MARGIN


def fit(data, model_dir, deadline, state):
    train, stop = state
    booster = xgb.train(
        PARAMS, train, num_boost_round=ROUNDS, evals=[(stop, "stop")], verbose_eval=50,
        callbacks=[xgb.callback.EarlyStopping(PATIENCE, save_best=True), Deadline(deadline)])
    print("best iteration", booster.num_boosted_rounds() - 1,
          "score", booster.attr("best_score"), flush=True)
    booster.save_model(str(model_dir / "model.ubj"))
    (model_dir / "meta.txt").write_text(
        " ".join(map(str, data.bin_edges)) + "\n" + " ".join(data.features) + "\n"
        + " ".join(f for f in data.features if f in data.categorical))


def load(model_dir):
    edges, features, categorical = (model_dir / "meta.txt").read_text().split("\n")
    booster = xgb.Booster(model_file=str(model_dir / "model.ubj"))
    if THREADS:
        booster.set_param({"nthread": THREADS})
    features, categorical = features.split(), categorical.split()
    return booster, [int(x) for x in edges.split()], features + ["bin_start"], \
        _types(features, categorical)


def predict(model, X, hist):
    booster, edges, names, types = model
    n = X.shape[0]
    stacked = np.vstack([np.hstack([X, np.full((n, 1), e, np.float32)]) for e in edges[:-1]])
    z = booster.predict(xgb.DMatrix(stacked, feature_names=names, feature_types=types,
                                    enable_categorical=True, missing=np.nan),
                        output_margin=True)
    return z.reshape(len(edges) - 1, n).T.astype(np.float64)

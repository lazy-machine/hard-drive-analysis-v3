"""The reference: the project's hazard_smart model under the block contract."""

from __future__ import annotations

import os
import time

import lightgbm as lgb
import numpy as np

from model import raw_hazard_logits
from survival import ExpandedSequence, expand

PARAMS = {
    "objective": "binary", "metric": "binary_logloss", "deterministic": True, "verbosity": -1,
    "force_row_wise": True, "seed": 42, "learning_rate": 0.03, "num_leaves": 31,
    "min_child_samples": 200, "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 5.0, "cat_smooth": 20,
    "num_threads": int(os.environ.get("HDA_THREADS", 0)),
}
WEIGHT_POWER = 0.5
ROUNDS = 2000
PATIENCE = 100


def _dataset(part, edges, names, categorical, reference=None):
    d, e, w = (part.meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, w_rows = expand(d, e, w, edges)
    rows = ExpandedSequence(np.array(part.X), idx, np.asarray(edges)[bins])
    return lgb.Dataset(rows, label=y, weight=w_rows ** WEIGHT_POWER, feature_name=names,
                       categorical_feature=categorical, params=PARAMS, reference=reference,
                       free_raw_data=True)


def prepare(data, model_dir):
    names = data.features + ["bin_start"]
    categorical = [f for f in data.features if f in data.categorical]
    train = _dataset(data.train, data.bin_edges, names, categorical)
    stop = _dataset(data.stop, data.bin_edges, names, categorical, reference=train)
    train.construct()
    stop.construct()
    return train, stop


def fit(data, model_dir, deadline, state):
    train, stop = state

    def out_of_time(env):
        if time.time() > deadline - 30:
            raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)

    booster = lgb.train(PARAMS, train, num_boost_round=ROUNDS, valid_sets=[stop],
                        valid_names=["stop"],
                        callbacks=[lgb.early_stopping(PATIENCE, verbose=False), out_of_time])
    booster.save_model(str(model_dir / "model.txt"), num_iteration=booster.best_iteration)
    print("best iteration", booster.best_iteration, flush=True)
    (model_dir / "edges.txt").write_text(" ".join(map(str, data.bin_edges)))


def load(model_dir):
    edges = [int(x) for x in (model_dir / "edges.txt").read_text().split()]
    return lgb.Booster(model_file=str(model_dir / "model.txt")), edges


def predict(model, X, hist):
    booster, edges = model
    return raw_hazard_logits(booster, X, edges)

"""CatBoost hazard model: the baseline's person-period setup on a different boosting engine.

One Logloss classifier over (snapshot, bin) rows with the bin start as a feature. CatBoost
brings oblivious (symmetric) trees, native categorical handling for model_code and vendor_code
(ordered target statistics), and its own border quantization. Boosting is Plain: Ordered is
meant for small data and costs a lot more per iteration at millions of rows. CatBoost is
slower per row than the other engines on CPU, so healthy rows are thinned to ROW_CAP with the
weight of each kept row divided by its keep probability.
"""

from __future__ import annotations

import os
import time

import catboost as cb
import numpy as np
import pandas as pd

from survival import expand

THREADS = int(os.environ.get("HDA_THREADS", -1)) or -1
PARAMS = {
    "loss_function": "Logloss", "eval_metric": "Logloss", "boosting_type": "Plain",
    "iterations": 20000, "learning_rate": 0.08, "depth": 7, "l2_leaf_reg": 10.0,
    "border_count": 128, "bootstrap_type": "Bernoulli", "subsample": 0.8,
    "rsm": 0.8, "max_ctr_complexity": 1, "od_type": "Iter", "od_wait": 100,
    "use_best_model": True, "metric_period": 5, "random_seed": 42, "thread_count": THREADS,
    "allow_writing_files": False, "verbose": 50,
}
WEIGHT_POWER = 0.5
ROW_CAP = 8_000_000         # expanded training rows kept; healthy rows beyond this are thinned
STOP_CAP = 1_500_000
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
    return idx, np.asarray(edges, dtype=np.float32)[bins], y, weight


def _frame(X, start, names, categorical):
    """Rows as a DataFrame: floats stay float32, categorical codes become int (never NaN)."""
    df = pd.DataFrame(np.hstack([X, start[:, None]]), columns=names)
    for c in categorical:
        df[c] = np.nan_to_num(df[c].to_numpy(), nan=-1).astype(np.int64)
    return df


def _pool(part, edges, names, categorical, cap, seed):
    idx, start, y, w = _expanded(part, edges, cap, seed)
    X = np.array(part.X)
    # build in slices so the float copy and the DataFrame do not both hold the whole thing
    df = pd.concat([_frame(X[idx[lo:lo + (1 << 20)]], start[lo:lo + (1 << 20)], names, categorical)
                    for lo in range(0, idx.size, 1 << 20)], ignore_index=True)
    pool = cb.Pool(df, label=y, weight=w, cat_features=categorical, thread_count=THREADS)
    print(f"matrix: {idx.size} rows", flush=True)
    return pool


def prepare(data, model_dir):
    names = data.features + ["bin_start"]
    categorical = [f for f in data.features if f in data.categorical]
    train = _pool(data.train, data.bin_edges, names, categorical, ROW_CAP, 1)
    stop = _pool(data.stop, data.bin_edges, names, categorical, STOP_CAP, 2)
    # border search is binning, not learning: do it here so the timed fit starts at trees
    train.quantize(border_count=PARAMS["border_count"], nan_mode="Min", random_seed=42)
    return train, stop


class Deadline:
    def __init__(self, deadline):
        self.deadline, self.last, self.slowest = deadline, time.time(), 0.0

    def after_iteration(self, info):
        now = time.time()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return not (now + 2 * self.slowest > self.deadline - MARGIN)


def fit(data, model_dir, deadline, state):
    train, stop = state
    model = cb.CatBoostClassifier(**PARAMS)
    model.fit(train, eval_set=stop, callbacks=[Deadline(deadline)])
    print("best iteration", model.get_best_iteration(), "trees", model.tree_count_, flush=True)
    model.save_model(str(model_dir / "model.cbm"))
    (model_dir / "meta.txt").write_text(
        " ".join(map(str, data.bin_edges)) + "\n" + " ".join(data.features) + "\n"
        + " ".join(f for f in data.features if f in data.categorical))


def load(model_dir):
    edges, features, categorical = (model_dir / "meta.txt").read_text().split("\n")
    model = cb.CatBoostClassifier()
    model.load_model(str(model_dir / "model.cbm"))
    features = features.split()
    return model, [int(x) for x in edges.split()], features + ["bin_start"], categorical.split()


def predict(model, X, hist):
    booster, edges, names, categorical = model
    n = X.shape[0]
    stacked = _frame(np.vstack([X] * (len(edges) - 1)),
                     np.repeat(np.asarray(edges[:-1], dtype=np.float32), n), names, categorical)
    z = booster.predict(cb.Pool(stacked, cat_features=categorical),
                        prediction_type="RawFormulaVal", thread_count=THREADS)
    return z.reshape(len(edges) - 1, n).T.astype(np.float64)

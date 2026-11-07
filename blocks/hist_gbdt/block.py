"""LightGBM on the baseline's person-period setup, plus features engineered from `hist`.

Question: do better features beat a better model? Same engine, expansion and weight power as
baseline_lgbm; the extra columns come from features.py, chosen for stability across years
(log ratios and rates per day, never absolute levels of size-driven quantities). Features are
computed per row in prepare and again in predict by one function.

Round 2: a bagged ensemble. Boosters with different seeds, leaf counts and feature fractions
share one binned dataset and split the fit budget; predict averages their logits.
At smoke scale only, fit() also prints a late-slice ablation by feature family (ablation.py).
"""

from __future__ import annotations

import os
import time

import lightgbm as lgb
import numpy as np

from features import NAMES, make_features
from model import raw_hazard_logits
from survival import ExpandedSequence, expand

THREADS = int(os.environ.get("HDA_THREADS", 0))
BASE = {
    "objective": "binary", "metric": "binary_logloss", "deterministic": True, "verbosity": -1,
    "force_row_wise": True, "learning_rate": 0.04, "min_child_samples": 200,
    "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "cat_smooth": 20,
    "num_threads": THREADS,
}
# min_child_samples is shared: it is a dataset parameter and the booster must agree with it
MEMBERS = [
    {"seed": 42, "num_leaves": 31, "feature_fraction": 0.5},
    {"seed": 7, "num_leaves": 48, "feature_fraction": 0.4},
    {"seed": 99, "num_leaves": 24, "feature_fraction": 0.6, "lambda_l2": 10.0},
]
WEIGHT_POWER = 0.5
ROUNDS = 2000
PATIENCE = 100
MIN_ROUNDS = 50           # a member cut by the clock below this is not worth keeping
SAFETY = 30               # seconds kept free for saving
SMOKE_ROWS = 3_000_000    # fewer expanded rows than this: smoke scale, run the ablation


def _dataset(part, edges, names, categorical, reference=None):
    d, e, w = (part.meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, w_rows = expand(d, e, w, edges)
    F = make_features(part.X, part.hist)
    rows = ExpandedSequence(F, idx, np.asarray(edges)[bins])
    return lgb.Dataset(rows, label=y, weight=w_rows ** WEIGHT_POWER, feature_name=names,
                       categorical_feature=categorical, params=BASE, reference=reference,
                       free_raw_data=True)


def prepare(data, model_dir):
    names = data.features + NAMES + ["bin_start"]
    categorical = [f for f in data.features if f in data.categorical]
    train = _dataset(data.train, data.bin_edges, names, categorical)
    stop = _dataset(data.stop, data.bin_edges, names, categorical, reference=train)
    train.construct()
    stop.construct()
    return train, stop


def fit(data, model_dir, deadline, state):
    train, stop = state
    (model_dir / "edges.txt").write_text(" ".join(map(str, data.bin_edges)))
    kept = 0
    for i, member in enumerate(MEMBERS):
        # each member gets an equal share of what is left; early stopping may use less
        left = deadline - SAFETY - time.time()
        if left <= 0:
            break
        member_end = time.time() + left / (len(MEMBERS) - i)
        params = {**BASE, **member}
        clocked = []

        def out_of_time(env, member_end=member_end, clocked=clocked):
            if time.time() > member_end:
                clocked.append(env.iteration)
                raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)

        t = time.time()
        booster = lgb.train(params, train, num_boost_round=ROUNDS, valid_sets=[stop],
                            valid_names=["stop"],
                            callbacks=[lgb.early_stopping(PATIENCE, verbose=False), out_of_time])
        best = booster.best_iteration or booster.current_iteration()
        print(f"member {i}: {member}, best iteration {best}, "
              f"stop logloss {booster.best_score['stop']['binary_logloss']:.5f}, "
              f"{time.time() - t:.0f}s", flush=True)
        if clocked and best < MIN_ROUNDS and kept:
            print(f"member {i} dropped: only {best} rounds before the clock", flush=True)
            continue
        booster.save_model(str(model_dir / f"model{kept}.txt"), num_iteration=best)
        kept += 1
    print("members kept", kept, flush=True)

    if train.num_data() < SMOKE_ROWS:
        import traceback

        import ablation
        categorical = [data.features.index(f) for f in data.features if f in data.categorical]
        try:
            ablation.run(data, THREADS or 2, deadline - SAFETY - 10, categorical)
        except Exception:                       # diagnostics must never cost the model
            traceback.print_exc()


def load(model_dir):
    edges = [int(x) for x in (model_dir / "edges.txt").read_text().split()]
    paths = sorted(model_dir.glob("model*.txt"))
    return [lgb.Booster(model_file=str(p)) for p in paths], edges


def predict(model, X, hist):
    boosters, edges = model
    F = make_features(X, hist)
    return np.mean([raw_hazard_logits(b, F, edges) for b in boosters], axis=0)

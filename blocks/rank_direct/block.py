"""rank_direct: train straight at the board metric, "fails within 30 days", one row per snapshot.

No survival expansion. The target is known_status at 30 days (unknown rows are dropped, not
treated as healthy). `fit` trains several candidates, scores each on `stop` with weighted
average precision, and keeps the best one:

  1. binary log loss, weight ** p for p in P_GRID (the tempering sweep)
  2. with the best p: focal loss, LambdaRank / XE-NDCG with one query per calendar month,
     last-N-years only, and exponential recency weights
  3. the winning configuration again at a lower learning rate, with the time that is left

Everything uses `train` and `stop` only. Output of `predict`: (n,) logits of "fails within 30".
"""

from __future__ import annotations

import json
import os
import time

import lightgbm as lgb
import numpy as np

from metrics import weighted_average_precision
from survival import known_status

HORIZON = 30
THREADS = int(os.environ.get("HDA_THREADS", 0))
P_GRID = [0.5, 0.25, 0.75, 1.0]
SCREEN_LR, FINAL_LR = 0.1, 0.04
SCREEN_ROUNDS, FINAL_ROUNDS = 400, 3000
PATIENCE = 50                # stop AP is noisy, so be patient
FINAL_PATIENCE = 150
SCREEN_SHARE = 0.65          # share of the budget for the screening stage
RESERVE = 45.0               # seconds kept for the last evaluation and the save
RECENT_YEARS = 3.0
HALF_LIFE_YEARS = 2.0
FOCAL_GAMMA = 2.0

BASE = {
    "verbosity": -1, "force_row_wise": True, "deterministic": True, "seed": 42,
    "num_leaves": 31, "min_child_samples": 200, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "cat_smooth": 20,
    "num_threads": THREADS, "metric": "average_precision", "max_bin": 255,
}


class State:
    pass


def prepare(data, model_dir):
    """Keep rows with a known 30-day status, sort them by date, bin them."""
    s = State()
    s.names = list(data.features)
    s.categorical = [f for f in data.features if f in data.categorical]
    parts = {}
    for name in ("train", "stop"):
        part = getattr(data, name)
        meta = part.meta
        status = known_status(meta["duration_days"].to_numpy(), meta["event"].to_numpy(), HORIZON)
        keep = np.flatnonzero(status >= 0)
        date = meta["date"].to_numpy()[keep]
        order = keep[np.argsort(date, kind="stable")]       # time order: groups are contiguous
        parts[name] = dict(
            X=np.ascontiguousarray(np.asarray(part.X)[order], dtype=np.float32),
            y=status[order].astype(np.float32), w=meta["weight"].to_numpy()[order],
            date=meta["date"].to_numpy()[order])
    s.parts = parts
    t = parts["train"]
    s.train = lgb.Dataset(t["X"], label=t["y"], weight=t["w"], feature_name=s.names,
                          categorical_feature=s.categorical, params=BASE, free_raw_data=True)
    s.train.construct()
    del t["X"]                                            # the binned copy is enough
    p = parts["stop"]
    s.stop = lgb.Dataset(p["X"], label=p["y"], weight=p["w"], feature_name=s.names,
                         categorical_feature=s.categorical, params=BASE, reference=s.train,
                         free_raw_data=False)
    s.stop.construct()
    # months as consecutive query groups (train is date-sorted)
    month = t["date"].astype("datetime64[M]")
    _, counts = np.unique(month, return_counts=True)     # sorted dates => sorted months
    s.groups = counts.astype(np.int32)
    s.age_years = (t["date"].max() - t["date"]).astype("timedelta64[D]").astype(float) / 365.25
    s.prior = float(np.average(t["y"], weights=t["w"]))
    s.stop_ap = (p["y"], p["w"])
    return s


def _focal_grad_hess(s, y, gamma):
    """Gradient and Hessian of focal loss w.r.t. the raw score (y in {0, 1})."""
    z = np.clip(np.where(y > 0.5, s, -s), -30.0, 30.0)  # the y = 0 loss is the y = 1 loss at -s
    p = 1.0 / (1.0 + np.exp(-z))
    p = np.clip(p, 1e-12, 1 - 1e-12)
    q = 1.0 - p
    lp = np.log(p)
    u = q ** gamma
    v = gamma * p * lp - q
    g = u * v
    h = -gamma * p * u * v + u * p * q * (gamma * (lp + 1.0) + 1.0)
    h = np.maximum(h, 0.5 * p * q)   # the true Hessian goes negative; keep Newton steps sane
    return np.where(y > 0.5, g, -g), h


class _Timer:
    def __init__(self, stop_at):
        self.stop_at = stop_at

    def __call__(self, env):
        if time.time() > self.stop_at:
            raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)


def _train(state, cfg, lr, rounds, stop_at, patience):
    """Train one candidate. Returns (booster, best_iteration, stop AP) or None."""
    params = {**BASE, "learning_rate": lr}
    train = state.train
    init = float(np.log(state.prior / (1 - state.prior)))
    w = state.parts["train"]["w"] ** cfg["p"]
    if cfg.get("half_life"):
        w = w * 0.5 ** (state.age_years / cfg["half_life"])
    if cfg["kind"] == "binary":
        params["objective"] = "binary"
    elif cfg["kind"] in ("lambdarank", "rank_xendcg"):
        params["objective"] = cfg["kind"]
        params["lambdarank_truncation_level"] = 100
    if cfg.get("recent_years"):
        keep = np.flatnonzero(state.age_years <= cfg["recent_years"])
        train = state.train.subset(keep, params=params)
        w = w[keep]
    train.set_weight(w)
    stop = state.stop
    if cfg["kind"] in ("lambdarank", "rank_xendcg"):
        train.set_group(state.groups)
    train.set_init_score(np.full(len(w), init))
    stop.set_init_score(np.full(len(state.stop_ap[0]), init))
    if cfg["kind"] == "focal":
        y = state.parts["train"]["y"]
        weight = w.astype(np.float64)

        def objective(preds, _data):
            g, h = _focal_grad_hess(preds, y, FOCAL_GAMMA)
            return g * weight, h * weight

        params["objective"] = objective
    # the lgb metric is a rank metric, so it needs no sigmoid; stop carries true weights
    booster = lgb.train(params, train, num_boost_round=rounds, valid_sets=[stop],
                        valid_names=["stop"],
                        callbacks=[lgb.early_stopping(patience, verbose=False), _Timer(stop_at)])
    best = booster.best_iteration or booster.current_iteration()
    z = booster.predict(state.parts["stop"]["X"], num_iteration=best, raw_score=True)
    y_stop, w_stop = state.stop_ap
    ap = weighted_average_precision(np.asarray(z), y_stop.astype(bool), w_stop)
    return booster, best, float(ap), init


def fit(data, model_dir, deadline, state):
    t0 = time.time()
    end = deadline - RESERVE
    screen_end = t0 + (end - t0) * SCREEN_SHARE
    results = []                                          # (name, cfg, ap, best_iter, secs)
    best = None                                           # (ap, name, cfg, booster, iter, init)

    def run(name, cfg, lr, rounds, stop_at, patience=PATIENCE):
        nonlocal best
        if time.time() > stop_at - 2:
            print(f"skip {name}: out of time", flush=True)
            return None
        t = time.time()
        booster, it, ap, init = _train(state, cfg, lr, rounds, stop_at, patience)
        print(f"{name}: stop AP {ap:.5f}  iters {it}  {time.time() - t:.0f}s", flush=True)
        results.append(dict(name=name, ap=ap, iters=it, seconds=round(time.time() - t, 1),
                            lr=lr))
        if best is None or ap > best[0]:
            best = (ap, name, cfg, booster, it, init, lr)
        return ap

    def cap(left):                                        # even split of what is left
        return min(screen_end, time.time() + max(5.0, (screen_end - time.time()) / left))

    plan_left = len(P_GRID) + 5
    for p in P_GRID:
        run(f"binary p={p}", dict(kind="binary", p=p), SCREEN_LR, SCREEN_ROUNDS, cap(plan_left))
        plan_left -= 1
    if best is None:
        raise RuntimeError("no candidate finished in the budget")
    p = best[2]["p"]
    follow = [
        (f"focal g={FOCAL_GAMMA:g} p={p}", dict(kind="focal", p=p)),
        (f"lambdarank/month p={p}", dict(kind="lambdarank", p=p)),
        (f"xendcg/month p={p}", dict(kind="rank_xendcg", p=p)),
        (f"binary last {RECENT_YEARS:g}y p={p}", dict(kind="binary", p=p, recent_years=RECENT_YEARS)),
        (f"binary half-life {HALF_LIFE_YEARS:g}y p={p}",
         dict(kind="binary", p=p, half_life=HALF_LIFE_YEARS)),
    ]
    for name, cfg in follow:
        try:
            run(name, cfg, SCREEN_LR, SCREEN_ROUNDS, cap(plan_left))
        except lgb.basic.LightGBMError as exc:             # one broken candidate must not sink the run
            print(f"{name} failed: {exc}", flush=True)
        plan_left -= 1
    # stage 2: the winner at a lower learning rate with what is left
    screened = best
    if time.time() < end - 30:
        run(f"final lr={FINAL_LR} {screened[1]}", screened[2], FINAL_LR, FINAL_ROUNDS, end,
            FINAL_PATIENCE)
    ap, name, cfg, booster, it, init, lr = best
    print(f"chosen: {name} (stop AP {ap:.5f}, lr {lr})", flush=True)
    booster.save_model(str(model_dir / "model.txt"), num_iteration=it)
    (model_dir / "meta.json").write_text(json.dumps(dict(init=init, chosen=name, ap=ap,
                                                        results=results)))


def load(model_dir):
    meta = json.loads((model_dir / "meta.json").read_text())
    return lgb.Booster(model_file=str(model_dir / "model.txt")), meta["init"]


def predict(model, X, hist):
    booster, init = model
    return booster.predict(np.asarray(X, dtype=np.float32), raw_score=True) + init

"""rank_direct: train straight at the board metric, "fails within 30 days", one row per snapshot.

No survival expansion. The target is known_status at 30 days (unknown rows are dropped, not
treated as healthy). `fit` trains several candidates, scores each on `stop` with weighted
average precision (the board metric, tie-aware, true weights), and keeps the best one:

  1. binary log loss, weight ** p for p in P_GRID (the tempering sweep)
  2. with the best p: the same model with hist_gbdt's engineered features (features.py),
     then with small, heavily regularised trees
  3. with the best p and feature set: focal loss, LambdaRank / XE-NDCG with query groups
     formed by time period, last-N-years only, exponential recency weights
  4. the winner again at a lower learning rate with the time that is left

Early stopping uses our own weighted AP on `stop`, evaluated every EVERY rounds (LightGBM's
native average_precision metric is logged next to it for comparison, not used to stop).
Everything uses `train` and `stop` only. Output of `predict`: (n,) logits of "fails within 30".
"""

from __future__ import annotations

import json
import os
import time

import lightgbm as lgb
import numpy as np

from features import NAMES, make_features
from metrics import weighted_average_precision
from survival import known_status

HORIZON = 30
THREADS = int(os.environ.get("HDA_THREADS", 0))
P_GRID = [0.5, 0.25, 0.75, 1.0]
SCREEN_LR, FINAL_LR = 0.08, 0.03
SCREEN_ROUNDS, FINAL_ROUNDS = 1000, 4000
PATIENCE, FINAL_PATIENCE = 100, 200       # in rounds
EVERY = 5                                 # own AP: every round up to EARLY, then every EVERY
EARLY = 30
SCREEN_SHARE = 0.65                       # share of the budget for the screening stage
RESERVE = 30.0                            # seconds kept for the save
RECENT_YEARS = 3.0
HALF_LIFE_YEARS = 2.0
FOCAL_GAMMA = 2.0
SHALLOW = {"num_leaves": 7, "min_child_samples": 1000, "lambda_l2": 50.0, "feature_fraction": 0.5}
MAX_QUERY = 10_000                        # LightGBM refuses larger query groups

BASE = {
    "verbosity": -1, "force_row_wise": True, "deterministic": True, "seed": 42,
    "num_leaves": 31, "min_child_samples": 200, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "cat_smooth": 20,
    "num_threads": THREADS, "max_bin": 255,
}


class State:
    pass


def _features(part, order):
    """make_features on the rows `order` of a Part, in chunks (X and hist are memory-mapped)."""
    out = None
    for lo in range(0, len(order), 100_000):
        rows = order[lo:lo + 100_000]
        F = make_features(np.asarray(part.X[rows]), np.asarray(part.hist[rows]))
        if out is None:
            out = np.empty((len(order), F.shape[1]), dtype=np.float32)
        out[lo:lo + len(rows)] = F
    return out


def query_groups(dates):
    """Consecutive query sizes: one per calendar month, a month split in equal parts when it
    holds more than MAX_QUERY rows. `dates` is sorted."""
    _, counts = np.unique(dates.astype("datetime64[M]"), return_counts=True)
    sizes = []
    for c in counts:
        k = -(-int(c) // MAX_QUERY)
        sizes += [int(x) for x in np.diff(np.linspace(0, c, k + 1).round().astype(int))]
    return np.array(sizes, dtype=np.int32)


def prepare(data, model_dir):
    """Keep rows with a known 30-day status, sort them by date, build both feature sets."""
    s = State()
    s.parts, orders = {}, {}
    for name in ("train", "stop"):
        meta = getattr(data, name).meta
        status = known_status(meta["duration_days"].to_numpy(), meta["event"].to_numpy(), HORIZON)
        keep = np.flatnonzero(status >= 0)
        order = keep[np.argsort(meta["date"].to_numpy()[keep], kind="stable")]
        orders[name] = order
        s.parts[name] = dict(y=status[order].astype(np.float32), w=meta["weight"].to_numpy()[order],
                             date=meta["date"].to_numpy()[order])
    categorical = [f for f in data.features if f in data.categorical]
    s.sets = {}
    for feats in (False, True):
        names = list(data.features) + (NAMES if feats else [])
        pair = {}
        for name in ("train", "stop"):
            part, p = getattr(data, name), s.parts[name]
            X = _features(part, orders[name]) if feats else np.asarray(part.X[orders[name]])
            pair[name] = lgb.Dataset(
                X, label=p["y"], weight=p["w"], feature_name=names,
                categorical_feature=categorical, params=BASE, free_raw_data=True,
                reference=pair.get("train"))
            pair[name].construct()
            del X
        s.sets[feats] = pair
    t = s.parts["train"]
    s.groups = query_groups(t["date"])
    s.age_years = (t["date"].max() - t["date"]).astype("timedelta64[D]").astype(float) / 365.25
    s.prior = float(np.average(t["y"], weights=t["w"]))
    return s


def _focal_grad_hess(s, y, gamma):
    """Gradient and Hessian of focal loss w.r.t. the raw score (y in {0, 1})."""
    z = np.clip(np.where(y > 0.5, s, -s), -30.0, 30.0)   # the y = 0 loss is the y = 1 loss at -s
    p = np.clip(1.0 / (1.0 + np.exp(-z)), 1e-12, 1 - 1e-12)
    q = 1.0 - p
    lp = np.log(p)
    u = q ** gamma
    v = gamma * p * lp - q
    g = u * v
    h = -gamma * p * u * v + u * p * q * (gamma * (lp + 1.0) + 1.0)
    h = np.maximum(h, 0.5 * p * q)   # the true Hessian goes negative; keep Newton steps sane
    return np.where(y > 0.5, g, -g), h


class Watch:
    """Own weighted AP on stop every EVERY rounds, early stopping on it, and the time limit.

    Passed to lgb.train as feval (computes the AP) and as a callback (decides to stop).
    """

    def __init__(self, y, w, patience, stop_at):
        self.y, self.w, self.patience, self.stop_at = y.astype(bool), w, patience, stop_at
        self.rounds = 0
        self.curve = {}                    # round -> AP
        self.best_round, self.best_ap = 0, -1.0

    def feval(self, preds, _data):
        self.rounds += 1
        if self.rounds <= EARLY or self.rounds % EVERY == 0:
            ap = weighted_average_precision(np.asarray(preds), self.y, self.w)
            self.curve[self.rounds] = ap
            if ap > self.best_ap:
                self.best_round, self.best_ap = self.rounds, ap
        return "own_ap", self.curve[max(self.curve)], True

    def __call__(self, env):
        if time.time() > self.stop_at or self.rounds - self.best_round >= self.patience:
            raise lgb.callback.EarlyStopException(self.best_round - 1, env.evaluation_result_list)


def _train(state, cfg, lr, rounds, stop_at, patience):
    """Train one candidate. Returns (booster, best round, stop AP, init, curves)."""
    feats = cfg.get("feats", False)
    train, stop = state.sets[feats]["train"], state.sets[feats]["stop"]
    params = {**BASE, "learning_rate": lr, "metric": ["average_precision"]}
    if cfg.get("shallow"):                 # against memorising single drives (near-duplicate rows)
        params.update(SHALLOW)
    init = float(np.log(state.prior / (1 - state.prior)))
    w = state.parts["train"]["w"] ** cfg["p"]
    if cfg.get("half_life"):
        w = w * 0.5 ** (state.age_years / cfg["half_life"])
    y = state.parts["train"]["y"]
    if cfg["kind"] == "binary":
        params["objective"] = "binary"
        params["metric"].append("binary_logloss")
    elif cfg["kind"] in ("lambdarank", "rank_xendcg"):
        params["objective"] = cfg["kind"]
        params["lambdarank_truncation_level"] = 100
    if cfg.get("recent_years"):
        keep = np.flatnonzero(state.age_years <= cfg["recent_years"])
        train = train.subset(keep, params=params)
        w, y = w[keep], y[keep]
    train.set_weight(w)
    if cfg["kind"] in ("lambdarank", "rank_xendcg"):
        train.set_group(state.groups)
    train.set_init_score(np.full(len(w), init))
    stop.set_init_score(np.full(stop.num_data(), init))
    if cfg["kind"] == "focal":
        weight = w.astype(np.float64)

        def objective(preds, _data):
            g, h = _focal_grad_hess(preds, y, FOCAL_GAMMA)
            return g * weight, h * weight

        params["objective"] = objective
    watch = Watch(state.parts["stop"]["y"], state.parts["stop"]["w"], patience, stop_at)
    record = {}
    booster = lgb.train(params, train, num_boost_round=rounds, valid_sets=[stop],
                        valid_names=["stop"], feval=watch.feval,
                        callbacks=[watch, lgb.record_evaluation(record)])
    return booster, watch.best_round, watch.best_ap, init, (watch.curve, record["stop"])


def _show_curve(curve, record):
    """AP over rounds: ours, LightGBM's native one (record has every round), and log loss."""
    rounds = sorted(curve)
    picks = sorted({r for r in rounds if r in (1, 2, 3, 5, 10, 20) or r % 25 == 0})
    native = record.get("average_precision", [])
    loss = record.get("binary_logloss", [])
    cells = []
    for r in picks:
        if r > len(native):                  # the stopping callback ran before the recorder
            break
        cell = f"{r}:{curve[r]:.4f}"
        if native:
            cell += f"/{native[r - 1]:.4f}"
        if loss:
            cell += f"/{loss[r - 1]:.4f}"
        cells.append(cell)
    print("  curve round:ownAP/nativeAP" + ("/logloss" if loss else "") + "  " + " ".join(cells),
          flush=True)


def fit(data, model_dir, deadline, state):
    t0 = time.time()
    end = deadline - RESERVE
    screen_end = t0 + (end - t0) * SCREEN_SHARE
    results = []
    best = None                                           # (ap, name, cfg, booster, round, init, lr)

    def run(name, cfg, lr, rounds, stop_at, patience=PATIENCE):
        nonlocal best
        if time.time() > stop_at - 2:
            print(f"skip {name}: out of time", flush=True)
            return None
        t = time.time()
        booster, rnd, ap, init, (curve, record) = _train(state, cfg, lr, rounds, stop_at, patience)
        print(f"{name}: stop AP {ap:.5f}  best round {rnd} of {max(curve)}  "
              f"{time.time() - t:.0f}s", flush=True)
        _show_curve(curve, record)
        results.append(dict(name=name, ap=ap, best_round=rnd, rounds=max(curve),
                            seconds=round(time.time() - t, 1), lr=lr))
        if best is None or ap > best[0]:
            best = (ap, name, cfg, booster, rnd, init, lr)
        return ap

    left = len(P_GRID) + 7                                # candidates still to run in stage 1

    def cap():                                            # even split of the screening time left
        return min(screen_end, time.time() + max(5.0, (screen_end - time.time()) / left))

    for p in P_GRID:
        run(f"binary p={p}", dict(kind="binary", p=p), SCREEN_LR, SCREEN_ROUNDS, cap())
        left -= 1
    if best is None:
        raise RuntimeError("no candidate finished in the budget")
    p = best[2]["p"]
    run(f"binary +features p={p}", dict(kind="binary", p=p, feats=True), SCREEN_LR,
        SCREEN_ROUNDS, cap())
    left -= 1
    feats = best[2].get("feats", False)
    run(f"binary {'+features ' if feats else ''}p={p} shallow",
        dict(kind="binary", p=p, feats=feats, shallow=True), SCREEN_LR, SCREEN_ROUNDS, cap())
    left -= 1
    shallow = bool(best[2].get("shallow"))
    tag = f"{'+features ' if feats else ''}{'shallow ' if shallow else ''}p={p}"
    follow = [
        (f"focal g={FOCAL_GAMMA:g} {tag}", dict(kind="focal")),
        (f"lambdarank/month {tag}", dict(kind="lambdarank")),
        (f"xendcg/month {tag}", dict(kind="rank_xendcg")),
        (f"binary last {RECENT_YEARS:g}y {tag}", dict(kind="binary", recent_years=RECENT_YEARS)),
        (f"binary half-life {HALF_LIFE_YEARS:g}y {tag}",
         dict(kind="binary", half_life=HALF_LIFE_YEARS)),
    ]
    for name, extra in follow:
        try:
            run(name, dict(p=p, feats=feats, shallow=shallow, **extra), SCREEN_LR, SCREEN_ROUNDS, cap())
        except lgb.basic.LightGBMError as exc:             # one broken candidate must not sink the run
            print(f"{name} failed: {exc}", flush=True)
        left -= 1
    if time.time() < end - 30:
        run(f"final lr={FINAL_LR} {best[1]}", best[2], FINAL_LR, FINAL_ROUNDS, end, FINAL_PATIENCE)
    ap, name, cfg, booster, rnd, init, lr = best
    print(f"chosen: {name} (stop AP {ap:.5f}, lr {lr}, round {rnd})", flush=True)
    booster.save_model(str(model_dir / "model.txt"), num_iteration=rnd)
    (model_dir / "meta.json").write_text(json.dumps(dict(
        init=init, chosen=name, ap=ap, feats=bool(cfg.get("feats", False)), results=results)))


def load(model_dir):
    meta = json.loads((model_dir / "meta.json").read_text())
    return lgb.Booster(model_file=str(model_dir / "model.txt")), meta["init"], meta["feats"]


def predict(model, X, hist):
    booster, init, feats = model
    F = make_features(X, hist) if feats else np.asarray(X, dtype=np.float32)
    return booster.predict(F, raw_score=True) + init

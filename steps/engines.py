"""Alternative prediction engines next to LightGBM (model.py): XGBoost, CatBoost, PyTorch.

Every engine fits the study's discrete-time hazard on the same data as model.train: the
train snapshots, the early-stopping half of the validation drives, tempered
inverse-probability weights (`weight_power`) and the actuarial person-period labels of
survival.expand. A saved model gives predict one thing: an uncalibrated logit per hazard
bin. That logit is calibrated per bin on the other validation half exactly as for
LightGBM, so two models differ only in the learner and evaluate compares them like any
other pair.

Engines (params.engine):
- "xgboost": boosted trees on the person-period rows (snapshot features + bin start),
  streamed in batches like the LightGBM steps. params.device is "cpu", or "cuda" for a
  ROCm build of XGBoost (the PyPI wheel has no AMD support). A missing value is passed as
  XGB_MISSING, below every real value: with NaN in the data XGBoost stores the binned
  matrix sparse, about 630 bytes per person-period row against 66, which does not fit at
  full scale. A tree still separates missing from real values with one split, but missing
  always sits on the low side instead of taking a learned default direction.
- "xgboost_aft": an accelerated failure time model on the snapshots themselves, without
  the expansion: log T = f(x) + sigma * Z. A failure on day d is interval-censored in
  [d, d + 1), a snapshot censored at d is right-censored at d + 1. The bin logits come from
  the fitted survival curve at the bin edges, so this is the one engine whose curve has a
  parametric shape.
- "catboost": oblivious trees on the person-period rows. CatBoost cannot stream batches,
  so the expanded matrix goes through a memory-mapped file in build/tmp. Missing values
  keep CatBoost's own handling (treated as below the minimum).
- "torch": the neural networks, in neural.py (its own module, so changing them does not
  invalidate the tree engines' checkpoints). They share run() and load() from here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from common import Progress, load_snapshots, load_study, val_roles, write_json
from model import _platt, _rows, _subset, model_features
from survival import expand

ENGINES = ("xgboost", "xgboost_aft", "catboost", "torch")
TREES = ("xgboost", "xgboost_aft", "catboost")
CHUNK = 200_000
XGB_MISSING = -1e9      # below every feature value (the most negative trend is about -2e5)


def _threads() -> int:
    return int(os.environ.get("HDA_THREADS", 0)) or os.cpu_count() or 4


# -- shared: data, calibration, metadata ----------------------------------------------------

def _load(ctx, p, study, schema):
    """Features, train / early-stopping / calibration parts, as in model.train."""
    features = model_features(schema, p["features"], p.get("include", ()), p.get("exclude", ()))
    meta_tr, X_tr = load_snapshots(ctx.inputs["snapshots"], ["train"], features)
    meta_all, X_all = load_snapshots(ctx.inputs["snapshots"], ["val"], features)
    calib = val_roles(meta_all["serial_number"], study["split"]["calibration_share"])
    parts = {"train": (meta_tr, X_tr), "early": _subset(meta_all, X_all, ~calib),
             "calib": _subset(meta_all, X_all, calib)}
    if min(m["event"].sum() for m, _ in parts.values()) == 0:
        raise ValueError("train and both validation parts need at least one failure each")
    return features, parts


def _with_bin(X: np.ndarray, start: float) -> np.ndarray:
    return np.hstack([X, np.full((X.shape[0], 1), start, np.float32)])


def calibrate(z: np.ndarray, meta, X, study, log) -> tuple[list, dict]:
    """Platt coefficients per bin from raw logits z (n, bins) of the calibration
    snapshots, with the true weights (as model.calibrate does for LightGBM)."""
    data, y, w, bins = _rows("hazard", meta, X, study)
    coefs, notes = [], {"fallback_bins": [], "fixed_slope_bins": []}
    for k in range(z.shape[1]):
        m = bins == k
        if y[m].sum() == 0:
            raise ValueError(f"no validation failure in bin {k}: cannot calibrate it")
        coef, fixed = _platt(z[data.idx[m], k], y[m], w[m], f"bin {k}", log)
        coefs.append(coef)
        notes["fixed_slope_bins"] += [k] if fixed else []
    return coefs, notes


def dense_targets(meta, edges: list[int], power: float) -> tuple[np.ndarray, np.ndarray]:
    """Per-snapshot label and weight in every bin, shape (n, bins): the person-period rows
    of survival.expand folded back onto their snapshots. Weight 0 = not at risk."""
    d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    idx, bins, y, w_rows = expand(d, e, w, edges)
    K = len(edges) - 1
    Y = np.zeros((len(d), K), np.float32)
    W = np.zeros((len(d), K), np.float32)
    Y[idx, bins] = y
    W[idx, bins] = w_rows ** power
    return Y, W


def train(ctx):
    """A tree engine step (xgboost, xgboost_aft, catboost)."""
    engine = ctx.params["engine"]
    if engine not in TREES:
        raise ValueError(f"engines:train fits {', '.join(TREES)}; '{engine}' is not one "
                         "(the torch engine is neural:train)")
    fit = {"xgboost": _fit_xgboost, "xgboost_aft": _fit_aft, "catboost": _fit_catboost}[engine]
    return run(ctx, fit)


def run(ctx, fit):
    """One engine model: fit, save, calibrate, write the metadata predict reads."""
    log = Progress(ctx)
    p = ctx.params
    engine = p["engine"]
    if engine not in ENGINES:
        raise ValueError(f"unknown engine '{engine}' (have {', '.join(ENGINES)})")
    if p.get("kind", "hazard") != "hazard":
        raise ValueError("the alternative engines fit hazard models only")
    study = load_study(ctx.inputs["study"])
    schema = json.loads(ctx.inputs["schema"].read_text())
    features, parts = _load(ctx, p, study, schema)
    categorical = [f for f in features if f in schema["categorical"]]
    log(f"{engine} / {p['features']}: {len(features)} features, "
        + ", ".join(f"{len(m)} {k}" for k, (m, _) in parts.items()) + " snapshots")

    model, info = fit(ctx, p, study, schema, features, categorical, parts, log)
    model.save(ctx.outputs["model"])
    names = features + (["bin_start"] if engine in ("xgboost", "catboost") else [])
    doc = {
        "name": ctx.name, "kind": "hazard", "engine": engine, "feature_set": p["features"],
        "features": features, "model_features": names, "categorical": categorical,
        "include": list(p.get("include", ())), "exclude": list(p.get("exclude", ())),
        "bin_edges": study["label"]["bin_edges"],
        "binary_horizon": study["label"]["binary_horizon"],
        "params": {k: v for k, v in p.items() if k not in ("features", "include", "exclude")},
        "weight_power": p.get("weight_power", 1.0), **info,
    }
    loaded = load(ctx.outputs["model"], doc)         # exactly what predict sees
    if getattr(model, "windows", None) is not None:  # sequence model: calibration windows
        loaded.windows = model.windows
    model = loaded
    meta_cal, X_cal = parts["calib"]
    calibration, notes = calibrate(model.hazard_logits(X_cal), meta_cal, X_cal, study, log)
    log(f"calibration (a, b) per bin: {[[round(a, 3), round(b, 3)] for a, b in calibration]}")
    write_json(ctx.outputs["meta"], {**doc, "calibration": calibration,
                                     "calibration_snapshots": int(len(meta_cal)),
                                     "calibration_notes": notes})
    return {k: info[k] for k in ("best_iter", "val_loss", "train_rows", "val_rows") if k in info}


def load(path, info: dict):
    """The saved model of an engine step, with .hazard_logits(X) -> (n, bins)."""
    if info["engine"] == "torch":
        import neural
        return neural.TorchHazard.load(Path(path), info)
    return {"xgboost": XGBHazard, "xgboost_aft": XGBAFT,
            "catboost": CatBoostHazard}[info["engine"]].load(Path(path), info)


def _every(n, log, what):
    """A progress line every n boosting rounds (the tree libraries print nothing here)."""
    def report(i, metrics):
        if (i + 1) % n == 0:
            log(f"{what} round {i + 1}: " + ", ".join(f"{k} {v:.6g}" for k, v in metrics.items()))
    return report


# -- XGBoost on person-period rows ----------------------------------------------------------

def _xgb_types(names, categorical):
    return ["c" if n in categorical else "q" for n in names]


def _xgb_dense(rows: np.ndarray) -> np.ndarray:
    """Missing values as XGB_MISSING, so XGBoost keeps its dense binned layout."""
    return np.where(np.isnan(rows), np.float32(XGB_MISSING), rows)


def _xgb_progress(log, n=50):
    import xgboost as xgb

    report = _every(n, log, "xgboost")

    class Progress(xgb.callback.TrainingCallback):
        def after_iteration(self, model, epoch, evals_log):
            report(epoch, {f"val {k}": v[-1] for k, v in evals_log.get("val", {}).items()})
            return False

    return Progress()


def _person_period_iter(X, idx, bin_start, y, w, names, types, batch=1 << 20):
    import xgboost as xgb

    class Batches(xgb.DataIter):
        """Expanded rows X[idx] + bin start, one batch at a time (never materialised)."""

        def __init__(self):
            self.pos = 0
            super().__init__(cache_prefix=None)

        def next(self, input_data):
            if self.pos >= idx.size:
                return 0
            sl = slice(self.pos, self.pos + batch)
            rows = _xgb_dense(np.hstack([X[idx[sl]], bin_start[sl, None]]))
            input_data(data=rows, label=y[sl], weight=w[sl], feature_names=names,
                       feature_types=types)
            self.pos += batch
            return 1

        def reset(self):
            self.pos = 0

    return Batches()


def _fit_xgboost(ctx, p, study, schema, features, categorical, parts, log):
    import xgboost as xgb

    edges = study["label"]["bin_edges"]
    power = p.get("weight_power", 1.0)
    names = features + ["bin_start"]
    types = _xgb_types(names, categorical)
    params = {"objective": "binary:logistic", "eval_metric": "logloss", "tree_method": "hist",
              "device": p.get("device", "cpu"), "seed": p["seed"], "nthread": _threads(),
              **p["xgb"]}
    mats = {}
    stats = {}
    for part in ("train", "early"):
        meta, X = parts[part]
        d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
        idx, bins, y, w_rows = expand(d, e, w, edges)
        it = _person_period_iter(X, idx, np.asarray(edges, np.float32)[bins], y,
                                 w_rows ** power, names, types)
        mats[part] = xgb.QuantileDMatrix(it, max_bin=params.get("max_bin", 256),
                                         enable_categorical=True,
                                         ref=mats.get("train"))
        stats[part] = (int(y.size), int(y.sum()))
    log(f"person-period rows: train {stats['train']}, early stopping {stats['early']} "
        "(rows, events)")
    history: dict = {}
    booster = xgb.train(params, mats["train"], num_boost_round=p["num_boost_round"],
                        evals=[(mats["early"], "val")],
                        early_stopping_rounds=p["early_stopping_rounds"], evals_result=history,
                        verbose_eval=False, callbacks=[_xgb_progress(log)])
    best = booster.best_iteration
    val_loss = history["val"]["logloss"][best]
    log(f"best iteration {best + 1}, val logloss {val_loss:.6g}")
    booster = booster[: best + 1]
    gain = booster.get_score(importance_type="total_gain")
    return XGBHazard(booster, names, types, edges), {
        "best_iter": best + 1, "val_loss": val_loss, "val_metric": "logloss",
        "train_rows": stats["train"][0], "train_events": stats["train"][1],
        "val_rows": stats["early"][0], "val_events": stats["early"][1],
        "importance_gain": dict(sorted(((n, float(gain.get(n, 0.0))) for n in names),
                                       key=lambda t: -t[1])),
    }


class XGBHazard:
    def __init__(self, booster, names, types, edges):
        self.booster, self.names, self.types, self.edges = booster, names, types, edges

    def save(self, path: Path):
        self.booster.save_model(str(path))

    @classmethod
    def load(cls, path: Path, info: dict):
        import xgboost as xgb

        booster = xgb.Booster(model_file=str(path))
        booster.set_param({"nthread": _threads()})
        if info.get("params", {}).get("device"):
            booster.set_param({"device": info["params"]["device"]})
        names = info["model_features"] if "model_features" in info else booster.feature_names
        return cls(booster, names, _xgb_types(names, info["categorical"]), info["bin_edges"])

    def hazard_logits(self, X: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        K = len(self.edges) - 1
        z = np.empty((X.shape[0], K))
        for lo in range(0, X.shape[0], CHUNK):
            part = X[lo:lo + CHUNK]
            for k in range(K):
                dm = xgb.DMatrix(_xgb_dense(_with_bin(part, self.edges[k])),
                                 feature_names=self.names, feature_types=self.types,
                                 enable_categorical=True, nthread=_threads())
                z[lo:lo + CHUNK, k] = self.booster.predict(dm, output_margin=True)
        return z


# -- XGBoost accelerated failure time on snapshots ------------------------------------------

def aft_bounds(meta) -> tuple[np.ndarray, np.ndarray]:
    """Lower and upper bound of the failure time in days after the snapshot."""
    d = meta["duration_days"].to_numpy().astype(np.float64)
    e = meta["event"].to_numpy().astype(bool)
    return np.where(e, d, d + 1.0), np.where(e, d + 1.0, np.inf)


def _aft_log_survival(z: np.ndarray, dist: str) -> np.ndarray:
    """log P(Z > z) for the standardized AFT error distribution."""
    from scipy.special import log_ndtr

    if dist == "normal":
        return log_ndtr(-z)
    if dist == "logistic":
        return -np.logaddexp(0.0, z)
    if dist == "extreme":            # minimum Gumbel: F(z) = 1 - exp(-exp(z))
        return -np.exp(np.minimum(z, 700.0))
    raise ValueError(f"unknown AFT distribution '{dist}'")


def aft_hazard_logits(mu: np.ndarray, sigma: float, dist: str, edges: list[int]) -> np.ndarray:
    """logit of P(fail in bin k | alive at its start) from the AFT location mu = E[log T]."""
    with np.errstate(divide="ignore"):
        log_t = np.log(np.asarray(edges, dtype=float))          # log 0 = -inf: S(0) = 1
    zz = (log_t[None, :] - mu[:, None]) / sigma
    log_s = _aft_log_survival(zz, dist)
    log_s[:, 0] = 0.0
    delta = np.diff(log_s, axis=1)                                # log S(b) - log S(a) <= 0
    delta = np.minimum(delta, -1e-12)
    h = -np.expm1(delta)
    return np.log(np.maximum(h, 1e-300)) - delta                  # log h - log(1 - h)


def _fit_aft(ctx, p, study, schema, features, categorical, parts, log):
    import xgboost as xgb

    power = p.get("weight_power", 1.0)
    types = _xgb_types(features, categorical)
    aft = p["aft"]
    params = {"objective": "survival:aft", "eval_metric": "aft-nloglik", "tree_method": "hist",
              "aft_loss_distribution": aft["distribution"],
              "aft_loss_distribution_scale": aft["scale"], "device": p.get("device", "cpu"),
              "seed": p["seed"], "nthread": _threads(), **p["xgb"]}
    mats = {}
    for part in ("train", "early"):
        meta, X = parts[part]
        lo, hi = aft_bounds(meta)
        mats[part] = xgb.QuantileDMatrix(
            _xgb_dense(X), label_lower_bound=lo, label_upper_bound=hi,
            weight=meta["weight"].to_numpy() ** power, feature_names=features,
            feature_types=types, enable_categorical=True,
            max_bin=params.get("max_bin", 256), ref=mats.get("train"))
    history: dict = {}
    booster = xgb.train(params, mats["train"], num_boost_round=p["num_boost_round"],
                        evals=[(mats["early"], "val")],
                        early_stopping_rounds=p["early_stopping_rounds"], evals_result=history,
                        verbose_eval=False, callbacks=[_xgb_progress(log)])
    best = booster.best_iteration
    val_loss = history["val"]["aft-nloglik"][best]
    log(f"best iteration {best + 1}, val aft-nloglik {val_loss:.6g}")
    booster = booster[: best + 1]
    gain = booster.get_score(importance_type="total_gain")
    meta_tr, _ = parts["train"]
    return XGBAFT(booster, features, types, study["label"]["bin_edges"], aft), {
        "best_iter": best + 1, "val_loss": val_loss, "val_metric": "aft-nloglik",
        "train_rows": int(len(meta_tr)), "train_events": int(meta_tr["event"].sum()),
        "val_rows": int(len(parts["early"][0])),
        "val_events": int(parts["early"][0]["event"].sum()),
        "importance_gain": dict(sorted(((n, float(gain.get(n, 0.0))) for n in features),
                                       key=lambda t: -t[1])),
    }


class XGBAFT(XGBHazard):
    def __init__(self, booster, names, types, edges, aft):
        super().__init__(booster, names, types, edges)
        self.aft = aft

    @classmethod
    def load(cls, path: Path, info: dict):
        base = XGBHazard.load(path, info)
        return cls(base.booster, info["features"], _xgb_types(info["features"],
                                                              info["categorical"]),
                   info["bin_edges"], info["params"]["aft"])

    def hazard_logits(self, X: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        mu = np.concatenate([
            self.booster.predict(xgb.DMatrix(_xgb_dense(X[lo:lo + CHUNK]),
                                             feature_names=self.names, feature_types=self.types,
                                             enable_categorical=True, nthread=_threads()),
                                 output_margin=True)
            for lo in range(0, X.shape[0], CHUNK)]).astype(np.float64)
        return aft_hazard_logits(mu, self.aft["scale"], self.aft["distribution"], self.edges)


# -- CatBoost on person-period rows ---------------------------------------------------------

def _catboost_data(X, idx, bin_start, categorical_pos, tmp: Path | None):
    """catboost.FeaturesData for X[idx] + bin start. Numerical columns go through a
    memory-mapped float32 file when `tmp` is given (the expanded matrix does not fit in RAM
    next to CatBoost's own copy); categorical codes become shared byte strings."""
    import catboost as cb

    num_pos = [j for j in range(X.shape[1]) if j not in categorical_pos]
    shape = (idx.size, len(num_pos) + 1)
    if tmp is not None:
        tmp.mkdir(parents=True, exist_ok=True)
        num = np.memmap(tmp / "expanded.f32", dtype=np.float32, mode="w+", shape=shape)
    else:
        num = np.empty(shape, np.float32)
    for lo in range(0, idx.size, 1 << 21):
        sl = slice(lo, lo + (1 << 21))
        num[sl, :-1] = X[idx[sl]][:, num_pos]
        num[sl, -1] = bin_start[sl]
    if not categorical_pos:
        return cb.FeaturesData(num_feature_data=num)
    codes = X[np.ix_(idx, categorical_pos)].astype(np.int64)
    levels = np.array([str(i).encode() for i in range(int(codes.max()) + 1)], dtype=object)
    return cb.FeaturesData(num_feature_data=num, cat_feature_data=levels[codes])


def _fit_catboost(ctx, p, study, schema, features, categorical, parts, log):
    import catboost as cb

    edges = study["label"]["bin_edges"]
    power = p.get("weight_power", 1.0)
    cat_pos = [features.index(f) for f in categorical]
    tmp = ctx.workdir / "build" / "tmp" / ctx.name
    pools, stats = {}, {}
    for part in ("train", "early"):
        meta, X = parts[part]
        d, e, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
        idx, bins, y, w_rows = expand(d, e, w, edges)
        data = _catboost_data(X, idx, np.asarray(edges, np.float32)[bins], cat_pos,
                              tmp if part == "train" else None)
        pools[part] = cb.Pool(data, label=y, weight=w_rows ** power)
        if part == "train":
            # binned now, so the raw float copy (12 GB at full scale) goes before training;
            # the validation pool is binned with these borders during fit
            pools[part].quantize(border_count=p["catboost"].get("border_count", 254))
            del data
            for f in tmp.glob("expanded.f32"):
                f.unlink()
        stats[part] = (int(y.size), int(y.sum()))
        log(f"{part}: {stats[part][0]} person-period rows, {stats[part][1]} events")
    model = cb.CatBoostClassifier(loss_function="Logloss", random_seed=p["seed"],
                                  thread_count=_threads(), allow_writing_files=False,
                                  iterations=p["num_boost_round"],
                                  early_stopping_rounds=p["early_stopping_rounds"],
                                  use_best_model=True, verbose=0, **p["catboost"])
    report = _every(50, log, "catboost")

    class Progress:
        def after_iteration(self, info):
            report(info.iteration - 1,
                   {f"val {k}": v[-1] for k, v in info.metrics.get("validation", {}).items()})
            return True

    model.fit(pools["train"], eval_set=pools["early"], callbacks=[Progress()])
    del pools
    best = model.get_best_iteration() + 1
    val_loss = model.get_best_score()["validation"]["Logloss"]
    log(f"best iteration {best}, val logloss {val_loss:.6g}")
    names = [f for f in features if f not in categorical] + ["bin_start"] + categorical
    gain = model.get_feature_importance()
    return CatBoostHazard(model, cat_pos, edges), {
        "best_iter": best, "val_loss": val_loss, "val_metric": "logloss",
        "train_rows": stats["train"][0], "train_events": stats["train"][1],
        "val_rows": stats["early"][0], "val_events": stats["early"][1],
        "importance_gain": dict(sorted(((n, float(g)) for n, g in zip(names, gain, strict=True)),
                                       key=lambda t: -t[1])),
    }


class CatBoostHazard:
    def __init__(self, model, categorical_pos, edges):
        self.model, self.categorical_pos, self.edges = model, categorical_pos, edges

    def save(self, path: Path):
        self.model.save_model(str(path))

    @classmethod
    def load(cls, path: Path, info: dict):
        import catboost as cb

        model = cb.CatBoostClassifier()
        model.load_model(str(path))
        pos = [info["features"].index(f) for f in info["categorical"]]
        return cls(model, pos, info["bin_edges"])

    def hazard_logits(self, X: np.ndarray) -> np.ndarray:
        import catboost as cb

        K = len(self.edges) - 1
        z = np.empty((X.shape[0], K))
        for lo in range(0, X.shape[0], CHUNK):
            part = X[lo:lo + CHUNK]
            idx = np.arange(part.shape[0])
            for k in range(K):
                data = _catboost_data(part, idx, np.full(idx.size, self.edges[k], np.float32),
                                      self.categorical_pos, None)
                z[lo:lo + CHUNK, k] = self.model.predict(cb.Pool(data),
                                                         prediction_type="RawFormulaVal",
                                                         thread_count=_threads())
        return z

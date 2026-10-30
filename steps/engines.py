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
  ROCm build of XGBoost (the PyPI wheel has no AMD support).
- "xgboost_aft": an accelerated failure time model on the snapshots themselves, without
  the expansion: log T = f(x) + sigma * Z. A failure on day d is interval-censored in
  [d, d + 1), a snapshot censored at d is right-censored at d + 1. The bin logits come from
  the fitted survival curve at the bin edges, so this is the one engine whose curve has a
  parametric shape.
- "catboost": oblivious trees on the person-period rows. CatBoost cannot stream batches,
  so the expanded matrix goes through a memory-mapped file in build/tmp.
- "torch": a neural logistic-hazard network (Gensheimer & Narasimhan 2018, Kvamme &
  Borgan 2021). One output per bin, trained on the snapshots with a mask of the bins each
  one is at risk in, which gives the same likelihood as the person-period rows without
  building them. arch "mlp", or "linear": one coefficient vector shared by every bin plus
  a per-bin intercept, the classic proportional-odds discrete-time model.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

from common import Progress, load_snapshots, load_study, val_roles, write_json
from model import _platt, _rows, _subset, model_features
from survival import expand

ENGINES = ("xgboost", "xgboost_aft", "catboost", "torch")
CHUNK = 200_000


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

    fit = {"xgboost": _fit_xgboost, "xgboost_aft": _fit_aft, "catboost": _fit_catboost,
           "torch": _fit_torch}[engine]
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
    return {"xgboost": XGBHazard, "xgboost_aft": XGBAFT, "catboost": CatBoostHazard,
            "torch": TorchHazard}[info["engine"]].load(Path(path), info)


# -- XGBoost on person-period rows ----------------------------------------------------------

def _xgb_types(names, categorical):
    return ["c" if n in categorical else "q" for n in names]


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
            input_data(data=np.hstack([X[idx[sl]], bin_start[sl, None]]), label=y[sl],
                       weight=w[sl], feature_names=names, feature_types=types)
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
                        verbose_eval=False)
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
                dm = xgb.DMatrix(_with_bin(part, self.edges[k]), feature_names=self.names,
                                 feature_types=self.types, enable_categorical=True,
                                 nthread=_threads())
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
            X, label_lower_bound=lo, label_upper_bound=hi,
            weight=meta["weight"].to_numpy() ** power, feature_names=features,
            feature_types=types, enable_categorical=True,
            max_bin=params.get("max_bin", 256), ref=mats.get("train"))
    history: dict = {}
    booster = xgb.train(params, mats["train"], num_boost_round=p["num_boost_round"],
                        evals=[(mats["early"], "val")],
                        early_stopping_rounds=p["early_stopping_rounds"], evals_result=history,
                        verbose_eval=False)
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
            self.booster.predict(xgb.DMatrix(X[lo:lo + CHUNK], feature_names=self.names,
                                             feature_types=self.types, enable_categorical=True,
                                             nthread=_threads()), output_margin=True)
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
        stats[part] = (int(y.size), int(y.sum()))
        log(f"{part}: {stats[part][0]} person-period rows, {stats[part][1]} events")
    model = cb.CatBoostClassifier(loss_function="Logloss", random_seed=p["seed"],
                                  thread_count=_threads(), allow_writing_files=False,
                                  iterations=p["num_boost_round"],
                                  early_stopping_rounds=p["early_stopping_rounds"],
                                  use_best_model=True, verbose=0, **p["catboost"])
    model.fit(pools["train"], eval_set=pools["early"])
    del pools
    for f in tmp.glob("expanded.f32"):
        f.unlink()
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


# -- PyTorch logistic-hazard network --------------------------------------------------------

def _device(want: str):
    import torch

    if want == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(want)


class Prep:
    """Feature scaling fitted on train: signed log1p of every numerical feature (SMART
    counters span 0 to 1e13), standardized, missing set to 0 with an indicator column for
    each feature that has missing values in train; categorical codes stay integers."""

    def __init__(self, numeric, categorical, cards, mean, std, missing):
        self.numeric, self.categorical, self.cards = numeric, categorical, cards
        self.mean, self.std, self.missing = mean, std, missing

    @classmethod
    def fit(cls, X, features, categorical, schema):
        numeric = [j for j, f in enumerate(features) if f not in categorical]
        cat = [features.index(f) for f in categorical]
        cards = [len(schema["categorical"][f]) for f in categorical]
        v = _signed_log(X[:, numeric])
        mean = np.nan_to_num(np.nanmean(v, axis=0))
        std = np.nan_to_num(np.nanstd(v, axis=0))
        std[std < 1e-6] = 1.0
        missing = [i for i in range(len(numeric)) if np.isnan(X[:, numeric[i]]).any()]
        return cls(numeric, cat, cards, mean.astype(np.float32), std.astype(np.float32),
                   missing)

    def transform(self, X) -> tuple[np.ndarray, np.ndarray]:
        v = (_signed_log(X[:, self.numeric]) - self.mean) / self.std
        isnan = np.isnan(v)
        flags = isnan[:, self.missing].astype(np.float32)
        v[isnan] = 0.0
        num = np.hstack([v, flags]).astype(np.float32)
        cat = X[:, self.categorical].astype(np.int64) if self.categorical else \
            np.zeros((X.shape[0], 0), np.int64)
        return num, cat

    @property
    def n_num(self) -> int:
        return len(self.numeric) + len(self.missing)

    def state(self) -> dict:
        import torch

        return {"numeric": self.numeric, "categorical": self.categorical, "cards": self.cards,
                "mean": torch.from_numpy(self.mean), "std": torch.from_numpy(self.std),
                "missing": self.missing}

    @classmethod
    def from_state(cls, s):
        return cls(list(s["numeric"]), list(s["categorical"]), list(s["cards"]),
                   s["mean"].numpy(), s["std"].numpy(), list(s["missing"]))


def _signed_log(v):
    return np.sign(v) * np.log1p(np.abs(v))


def _hazard_net(n_num: int, cards: list[int], K: int, arch: dict, n_channels: int = 0):
    """The network: embeddings + an MLP (or one shared linear score) over the snapshot
    features; with `n_channels`, a GRU over the daily window joins the MLP's output."""
    import torch
    from torch import nn

    class HazardNet(nn.Module):
        def __init__(self):
            super().__init__()
            kind = arch["type"]
            emb = [1 if kind == "linear" else min(16, (c + 1) // 2) for c in cards]
            self.emb = nn.ModuleList(nn.Embedding(c, d) for c, d in zip(cards, emb, strict=True))
            width = n_num + sum(emb)
            if kind == "linear":
                self.body = nn.Identity()
                self.shared = nn.Linear(width, 1, bias=False)
                self.bias = nn.Parameter(torch.zeros(K))
            elif kind in ("mlp", "gru"):
                layers, d = [], width
                for h in arch["hidden"]:
                    layers += [nn.Linear(d, h), nn.LayerNorm(h), nn.SiLU(),
                               nn.Dropout(arch.get("dropout", 0.0))]
                    d = h
                self.body = nn.Sequential(*layers)
                if kind == "gru":
                    self.rnn = nn.GRU(n_channels, arch["rnn_hidden"], batch_first=True)
                    d += arch["rnn_hidden"]
                self.head = nn.Linear(d, K)
            else:
                raise ValueError(f"unknown torch arch '{kind}' (linear, mlp, gru)")
            self.kind = kind

        def forward(self, num, cat, seq=None):
            x = torch.cat([num] + [e(cat[:, j]) for j, e in enumerate(self.emb)], dim=1)
            if self.kind == "linear":
                return self.shared(x) + self.bias
            x = self.body(x)
            if self.kind == "gru":
                with torch.autocast(seq.device.type, enabled=False):
                    _, h = self.rnn(seq.float())
                x = torch.cat([x, h[-1].to(x.dtype)], dim=1)
            return self.head(x)

    return HazardNet()


def _weighted_bce(z, Y, W):
    import torch.nn.functional as F

    return (F.binary_cross_entropy_with_logits(z.float(), Y, reduction="none") * W).sum()


def _train_net(net, forward, targets, cfg, dev, seed, log):
    """Mini-batch AdamW on the masked, weighted hazard likelihood with early stopping on
    the early-stopping drives. forward(part, rows) gives the logits of those rows;
    targets[part] = (Y, W) on the device. The learning rate halves after every epoch that
    does not improve, and training stops after `patience` such epochs."""
    import torch

    (Y_tr, W_tr), (Y_va, W_va) = targets["train"], targets["early"]
    n = Y_tr.shape[0]
    norm = float(W_tr.sum()) / n             # loss per snapshot, on the scale of a mean weight
    opt = torch.optim.AdamW(net.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    amp = dev.type == "cuda"
    gen = torch.Generator(device=dev).manual_seed(seed)

    def val_loss():
        net.eval()
        total = 0.0
        with torch.no_grad(), torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp):
            for lo in range(0, Y_va.shape[0], 1 << 16):
                rows = torch.arange(lo, min(lo + (1 << 16), Y_va.shape[0]), device=dev)
                total += float(_weighted_bce(forward("early", rows), Y_va[rows], W_va[rows]))
        net.train()
        return total / float(W_va.sum())

    best, best_state, best_epoch, bad, lr = math.inf, None, 0, 0, cfg["lr"]
    bs = cfg["batch_size"]
    for epoch in range(cfg["max_epochs"]):
        perm = torch.randperm(n, device=dev, generator=gen)
        for lo in range(0, n, bs):
            b = perm[lo:lo + bs]
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp):
                z = forward("train", b)
            loss = _weighted_bce(z, Y_tr[b], W_tr[b]) / (norm * b.numel())
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        v = val_loss()
        log(f"epoch {epoch + 1}: val logloss {v:.6g} (lr {lr:.2g})")
        if v < best - 1e-7:
            best, bad, best_epoch = v, 0, epoch + 1
            best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
        else:
            bad += 1
            lr *= 0.5
            for g in opt.param_groups:
                g["lr"] = lr
            if bad >= cfg["patience"]:
                break
    net.load_state_dict(best_state)
    log(f"best epoch {best_epoch}, val logloss {best:.6g}")
    return best_epoch, best


def _fit_torch(ctx, p, study, schema, features, categorical, parts, log):
    import torch

    edges = study["label"]["bin_edges"]
    K = len(edges) - 1
    cfg = p["torch"]
    torch.manual_seed(p["seed"])
    dev = _device(p.get("device", "auto"))
    meta_tr, X_tr = parts["train"]
    prep = Prep.fit(X_tr, features, categorical, schema)
    inputs, targets = {}, {}
    for part in ("train", "early"):
        meta, X = parts[part]
        num, cat = prep.transform(X)
        Y, W = dense_targets(meta, edges, p.get("weight_power", 1.0))
        inputs[part] = [torch.from_numpy(a).to(dev) for a in (num, cat)]
        targets[part] = [torch.from_numpy(a).to(dev) for a in (Y, W)]
    windows = None
    if cfg["arch"]["type"] == "gru":
        windows = PanelWindows.build(ctx.inputs["panel_dir"], ctx.inputs["snapshots"],
                                     ["train", "val"], study, prep, features, dev, log)
        # load_snapshots orders by split, so train rows come first, then val
        n_tr = len(meta_tr)
        early = ~val_roles(_val_serials(ctx), study["split"]["calibration_share"])
        rows = {"train": torch.arange(n_tr, device=dev),
                "early": torch.from_numpy(np.flatnonzero(early) + n_tr).to(dev)}
    net = _hazard_net(prep.n_num, prep.cards, K, cfg["arch"],
                      windows.channels if windows else 0).to(dev)
    log(f"device {dev}, {prep.n_num} numerical inputs ({len(prep.missing)} missing flags), "
        f"{len(prep.cards)} embeddings, {sum(x.numel() for x in net.parameters())} parameters"
        + (f", {windows.length}-day windows of {windows.channels} channels" if windows else ""))

    def forward(part, b):
        num, cat = inputs[part]
        if windows is None:
            return net(num[b], cat[b])
        return net(num[b], cat[b], windows.batch(rows[part][b]))

    best_epoch, best = _train_net(net, forward, targets, cfg, dev, p["seed"], log)
    model = TorchHazard(net.cpu(), prep, cfg["arch"], K, dev)
    if windows is not None:
        model.windows = windows.restricted(_calib_rows(ctx, study, len(meta_tr)))
    return model, {
        "best_iter": best_epoch, "val_loss": best, "val_metric": "logloss",
        "train_rows": int(len(meta_tr)), "train_events": int(meta_tr["event"].sum()),
        "val_rows": int(len(parts["early"][0])),
        "val_events": int(parts["early"][0]["event"].sum()),
        **({"window_days": windows.length, "needs_panel": True} if windows else {}),
    }


def _val_serials(ctx):
    import duckdb

    from common import q
    con = duckdb.connect()
    return con.sql(f"SELECT serial_number FROM read_parquet({q(ctx.inputs['snapshots'])}) "
                   "WHERE split = 'val' ORDER BY split, serial_number, date").df()["serial_number"]


def _calib_rows(ctx, study, n_train):
    """Rows of the calibration snapshots in the train + val window index."""
    calib = val_roles(_val_serials(ctx), study["split"]["calibration_share"])
    return np.flatnonzero(calib) + n_train


class PanelWindows:
    """Each snapshot's last `length` days of daily SMART readings, gathered on the device.

    The panel rows of the snapshots' drives sit in one fp16 matrix (drive by drive, day by
    day, scaled like the snapshot features: signed log1p, standardized, missing = 0). A
    snapshot is the row of its own day, `pos`, and the first row of its drive, `start`.
    Its window is rows pos - length + 1 .. pos, cut at the drive's first row; each step adds
    two channels, the days before the snapshot (/ length) and a 1 for a real row. Only past
    rows are used, and extract already cut train and validation drives at train_end."""

    def __init__(self, values, days, pos, start, length):
        self.values, self.days, self.pos, self.start, self.length = values, days, pos, start, length

    @property
    def channels(self) -> int:
        return self.values.shape[1] + 2

    @classmethod
    def build(cls, panel_dir, snapshots, splits, study, prep, features, dev, log):
        import duckdb
        import torch

        from common import q, smart_columns
        length = max(study["features"]["trend_windows"])
        cols = smart_columns(study)
        mean, std = _channel_scaling(prep, features, cols)
        con = duckdb.connect(config={"threads": _threads()})
        where = "split IN (" + ", ".join(q(s) for s in splits) + ")"
        con.sql(f"""CREATE TABLE keys AS SELECT row_number() OVER (ORDER BY split, serial_number,
                    date) - 1 AS i, serial_number, date FROM read_parquet({q(snapshots)})
                    WHERE {where}""")
        n = con.sql("SELECT count(*) FROM keys").fetchall()[0][0]
        pos = np.full(n, -1, np.int64)
        start = np.full(n, -1, np.int64)
        values, days, offset = [], [], 0
        for batch in sorted(Path(panel_dir).glob("batch=*")):
            src = f"read_parquet({q(str(batch) + '/*.parquet')})"
            con.sql(f"""CREATE OR REPLACE TABLE p AS SELECT row_number() OVER (ORDER BY
                        serial_number, date) - 1 AS r, serial_number, date,
                        date_diff('day', DATE '1970-01-01', date) AS epoch_day, {", ".join(cols)}
                        FROM {src} WHERE serial_number IN (SELECT serial_number FROM keys)""")
            t = con.sql("SELECT * FROM p ORDER BY r").fetch_arrow_table()
            block = np.empty((t.num_rows, len(cols)), np.float32)
            for j, c in enumerate(cols):
                block[:, j] = t.column(c).to_numpy(zero_copy_only=False)
            block = (_signed_log(block) - mean) / std
            values.append(np.nan_to_num(block, nan=0.0).astype(np.float16))
            days.append(t.column("epoch_day").to_numpy(zero_copy_only=False).astype(np.int32))
            hit = con.sql("""SELECT k.i, p.r, min(p.r) OVER (PARTITION BY p.serial_number) AS s
                             FROM p LEFT JOIN keys k USING (serial_number, date)""").df()
            hit = hit[hit["i"].notna()]
            pos[hit["i"].to_numpy(np.int64)] = hit["r"].to_numpy(np.int64) + offset
            start[hit["i"].to_numpy(np.int64)] = hit["s"].to_numpy(np.int64) + offset
            offset += t.num_rows
            del t, block
        if (pos < 0).any():
            raise ValueError(f"{int((pos < 0).sum())} snapshots have no panel row on their day")
        log(f"panel windows: {offset} daily rows of {len(cols)} channels for {n} snapshots")
        to = (lambda a: torch.from_numpy(a).to(dev)) if dev is not None else torch.from_numpy
        return cls(to(np.concatenate(values)), to(np.concatenate(days)), to(pos), to(start),
                   length)

    def batch(self, rows):
        """(rows, length, channels) windows, oldest day first, as float32."""
        import torch

        p, s = self.pos[rows], self.start[rows]
        back = torch.arange(self.length - 1, -1, -1, device=p.device)
        idx = p[:, None] - back[None, :]
        real = idx >= s[:, None]
        idx = torch.where(real, idx, p[:, None])
        x = self.values[idx].float() * real[..., None]
        age = (self.days[p][:, None] - self.days[idx]).float() / self.length * real
        return torch.cat([x, age[..., None], real[..., None].float()], dim=2)

    def restricted(self, rows):
        """The same panel, indexed by the given snapshot rows only."""
        import torch

        r = torch.as_tensor(rows, device=self.pos.device)
        return PanelWindows(self.values, self.days, self.pos[r], self.start[r], self.length)


def _channel_scaling(prep: Prep, features, cols):
    """Scaling of each panel column: the snapshot feature's, which Prep fitted on train."""
    by_name = {features[j]: i for i, j in enumerate(prep.numeric)}
    missing = [c for c in cols if c not in by_name]
    if missing:
        raise ValueError(f"the sequence model needs the SMART features {missing} for scaling")
    i = [by_name[c] for c in cols]
    return prep.mean[i], prep.std[i]


class TorchHazard:
    """A trained network. A sequence model also needs `windows` (PanelWindows) whose rows
    line up with the X passed to hazard_logits; predict and train attach them."""

    windows = None

    def __init__(self, net, prep: Prep, arch: dict, K: int, device):
        self.net, self.prep, self.arch, self.K, self.device = net, prep, arch, K, device

    def save(self, path: Path):
        import torch

        torch.save({"state_dict": self.net.state_dict(), "prep": self.prep.state(),
                    "arch": self.arch, "K": self.K,
                    "channels": self.windows.channels if self.windows else 0}, path)

    @classmethod
    def load(cls, path: Path, info: dict):
        import torch

        s = torch.load(path, map_location="cpu", weights_only=True)
        prep = Prep.from_state(s["prep"])
        net = _hazard_net(prep.n_num, prep.cards, s["K"], s["arch"], s.get("channels", 0))
        net.load_state_dict(s["state_dict"])
        dev = _device(info.get("params", {}).get("device", "auto"))
        return cls(net, prep, s["arch"], s["K"], dev)

    def hazard_logits(self, X: np.ndarray) -> np.ndarray:
        import torch

        if self.arch["type"] == "gru" and self.windows is None:
            raise ValueError("a sequence model needs its panel windows attached")
        net = self.net.to(self.device).eval()
        out = np.empty((X.shape[0], self.K))
        with torch.no_grad():
            for lo in range(0, X.shape[0], CHUNK):
                num, cat = self.prep.transform(X[lo:lo + CHUNK])
                args = [torch.from_numpy(num).to(self.device),
                        torch.from_numpy(cat).to(self.device)]
                if self.windows is not None:
                    rows = torch.arange(lo, min(lo + CHUNK, X.shape[0]), device=self.device)
                    args.append(self.windows.batch(rows))
                out[lo:lo + CHUNK] = net(*args).float().cpu().numpy()
        return out

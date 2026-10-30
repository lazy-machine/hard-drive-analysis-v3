"""The alternative engines: their survival math, and that each one learns a known signal."""

import numpy as np
import pandas as pd
import pytest

from engines import Prep, aft_bounds, aft_hazard_logits, dense_targets
from survival import expand

EDGES = [0, 7, 14, 30]


def test_dense_targets_hold_the_person_period_rows():
    meta = pd.DataFrame({"duration_days": [10, 0, 9, 40], "event": [1, 1, 0, 0],
                         "weight": [4.0, 1.0, 1.0, 9.0]})
    Y, W = dense_targets(meta, EDGES, power=0.5)
    idx, bins, y, w = expand(meta["duration_days"], meta["event"], meta["weight"], EDGES)
    assert (W > 0).sum() == idx.size
    np.testing.assert_array_equal(Y[idx, bins], y)
    np.testing.assert_allclose(W[idx, bins], w ** 0.5, rtol=1e-6)
    # not at risk: the snapshot that failed on day 10 has no row in bin 2
    assert W[0, 2] == 0 and Y[0, 1] == 1


def test_aft_bounds_follow_the_label_convention():
    meta = pd.DataFrame({"duration_days": [0, 5, 5], "event": [1, 1, 0]})
    lo, hi = aft_bounds(meta)
    np.testing.assert_array_equal(lo, [0, 5, 6])          # alive through day 5 -> T >= 6
    np.testing.assert_array_equal(hi, [1, 6, np.inf])     # failed on day 5 -> T in [5, 6)


@pytest.mark.parametrize("dist", ["normal", "logistic", "extreme"])
def test_aft_bin_hazards_rebuild_the_survival_curve(dist):
    from scipy import stats

    mu, sigma = np.array([1.5, 3.0, 6.0]), 0.8
    z = aft_hazard_logits(mu, sigma, dist, EDGES)
    h = 1 / (1 + np.exp(-z))
    S = np.cumprod(1 - h, axis=1)
    cdf = {"normal": stats.norm.cdf, "logistic": stats.logistic.cdf,
           "extreme": lambda x: 1 - np.exp(-np.exp(x))}[dist]
    expected = 1 - cdf((np.log(np.array(EDGES[1:]))[None, :] - mu[:, None]) / sigma)
    np.testing.assert_allclose(S, expected, rtol=1e-6, atol=1e-12)
    # a longer predicted life means a lower hazard in every bin
    assert (np.diff(z, axis=0) < 0).all()


def test_prep_scales_flags_missing_and_keeps_codes():
    X = np.array([[0.0, 1e12, 2], [np.nan, 10.0, 0], [5.0, 0.0, 1]], np.float32)
    schema = {"categorical": {"c": ["a", "b", "c"]}}
    prep = Prep.fit(X, ["x", "y", "c"], ["c"], schema)
    num, cat = prep.transform(X)
    assert num.shape == (3, 3)                      # x, y and the missing flag of x
    np.testing.assert_array_equal(num[:, 2], [0, 1, 0])
    assert np.isfinite(num).all() and np.abs(num[:, :2]).max() < 3
    np.testing.assert_array_equal(cat[:, 0], [2, 0, 1])
    again = Prep.from_state(prep.state()).transform(X)
    np.testing.assert_array_equal(again[0], num)


def _toy(n=6000, seed=0):
    """Snapshots whose time to failure shortens with x0; x1 is noise, c a categorical."""
    rng = np.random.default_rng(seed)
    X = np.column_stack([rng.normal(size=n), rng.normal(size=n),
                         rng.integers(0, 3, n)]).astype(np.float32)
    t = rng.exponential(40 * np.exp(-1.2 * X[:, 0]))
    censor = rng.uniform(5, 60, n)
    meta = pd.DataFrame({"duration_days": np.floor(np.minimum(t, censor)).astype(int),
                         "event": (t <= censor).astype(int), "weight": np.ones(n),
                         "serial_number": [f"s{i}" for i in range(n)]})
    return meta, X


@pytest.mark.parametrize("engine", ["xgboost", "xgboost_aft", "catboost", "torch"])
def test_engine_ranks_a_known_signal(engine, tmp_path):
    import engines

    study = {"label": {"bin_edges": EDGES}}
    schema = {"categorical": {"c": ["a", "b", "c"]}}
    features, categorical = ["x0", "x1", "c"], ["c"]
    parts = {"train": _toy(), "early": _toy(seed=1), "calib": _toy(seed=2)}
    p = {"seed": 1, "weight_power": 1.0, "num_boost_round": 60, "early_stopping_rounds": 10,
         "device": "cpu",
         "xgb": {"eta": 0.1, "max_depth": 3},
         "aft": {"distribution": "extreme", "scale": 1.0},
         "catboost": {"learning_rate": 0.1, "depth": 4},
         "torch": {"arch": {"type": "mlp", "hidden": [16], "dropout": 0.0}, "lr": 0.01,
                   "weight_decay": 0.0, "batch_size": 512, "max_epochs": 5, "patience": 2}}

    class Ctx:
        workdir = tmp_path
        name = "toy"

    fit = {"xgboost": engines._fit_xgboost, "xgboost_aft": engines._fit_aft,
           "catboost": engines._fit_catboost, "torch": engines._fit_torch}[engine]
    model, info = fit(Ctx, p, study, schema, features, categorical, parts, lambda *a: None)
    path = tmp_path / {"xgboost": "m.ubj", "xgboost_aft": "m.ubj", "catboost": "m.cbm",
                       "torch": "m.pt"}[engine]
    model.save(path)
    names = features + (["bin_start"] if engine in ("xgboost", "catboost") else [])
    loaded = engines.load(path, {"engine": engine, "features": features,
                                 "model_features": names, "categorical": categorical,
                                 "bin_edges": EDGES, "params": p})
    meta, X = parts["calib"]
    z = loaded.hazard_logits(X)
    assert z.shape == (len(X), len(EDGES) - 1) and np.isfinite(z).all()
    np.testing.assert_allclose(z, model.hazard_logits(X), rtol=1e-5, atol=1e-5)
    # higher x0 = earlier failure, so the first-bin hazard must rank with x0
    assert np.corrcoef(z[:, 0], X[:, 0])[0, 1] > 0.5

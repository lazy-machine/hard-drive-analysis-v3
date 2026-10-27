"""Survival math against hand-computed answers."""

import numpy as np
import pytest

from survival import (
    expand, failure_probability, hazards_to_survival, known_status, life_quantile,
    restricted_mean_life,
)

EDGES = [0, 7, 14, 30]


def rows_of(i, idx, bins, y, w):
    m = idx == i
    return list(zip(bins[m].tolist(), y[m].tolist(), np.round(w[m], 6).tolist()))


def test_expand_event_in_second_bin():
    # fails 10 days after the snapshot: survives bin 0, fails in bin 1, absent from bin 2
    out = expand([10], [1], [2.0], EDGES)
    assert rows_of(0, *out) == [(0, 0, 2.0), (1, 1, 2.0)]


def test_expand_event_on_snapshot_day():
    out = expand([0], [1], [1.0], EDGES)
    assert rows_of(0, *out) == [(0, 1, 1.0)]


def test_expand_censored_inside_bin_gets_partial_exposure():
    # alive through day 9 -> bin 0 fully survived, bin 1 (days 7..13) seen for 3 of 7 days
    out = expand([9], [0], [1.0], EDGES)
    assert rows_of(0, *out) == [(0, 0, 1.0), (1, 0, round(3 / 7, 6))]


def test_expand_censored_on_last_day_of_bin_is_full_survival():
    out = expand([13], [0], [1.0], EDGES)
    assert rows_of(0, *out) == [(0, 0, 1.0), (1, 0, 1.0)]


def test_expand_never_labels_after_the_last_edge():
    out = expand([100, 100], [1, 0], [1.0, 1.0], EDGES)
    assert out[2].sum() == 0 and len(out[0]) == 6


def test_expand_rejects_negative_duration():
    with pytest.raises(ValueError):
        expand([-1], [0], [1.0], EDGES)


def test_known_status():
    d = np.array([5, 29, 30, 28, 29, 40])
    e = np.array([1, 1, 1, 0, 0, 0])
    assert known_status(d, e, 30).tolist() == [1, 1, 0, -1, 0, 0]


def test_survival_and_quantiles():
    h = np.array([[0.1, 0.2, 0.5]])
    S = hazards_to_survival(h)
    assert np.allclose(S, [[0.9, 0.72, 0.36]])
    assert np.isclose(failure_probability(S, EDGES, 14), 0.28)
    assert np.isclose(failure_probability(S, EDGES, 0), 0.0)
    # S crosses 0.5 in the last bin (14..30): 0.72 -> 0.36, so at 14 + 16 * (0.22 / 0.36)
    assert np.isclose(life_quantile(S, EDGES, 0.5)[0], 14 + 16 * 0.22 / 0.36)
    assert np.isclose(life_quantile(S, EDGES, 0.1)[0], 7.0)
    assert np.isinf(life_quantile(S, EDGES, 0.9)[0])
    rmst = 7 * (1 + 0.9) / 2 + 7 * (0.9 + 0.72) / 2 + 16 * (0.72 + 0.36) / 2
    assert np.isclose(restricted_mean_life(S, EDGES)[0], rmst)


def test_quantile_when_survival_is_flat():
    S = hazards_to_survival(np.zeros((2, 3)))
    assert np.isinf(life_quantile(S, EDGES, 0.5)).all()
    assert np.allclose(restricted_mean_life(S, EDGES), 30)


def test_platt_recovers_known_coefficients():
    from survival import apply_platt, fit_platt

    rng = np.random.default_rng(3)
    z = rng.normal(-3, 1.5, 200_000)
    y = (rng.random(z.size) < apply_platt(z, [-0.7, 1.4])).astype(int)
    a, b = fit_platt(z, y, np.ones(z.size))
    assert abs(a + 0.7) < 0.08 and abs(b - 1.4) < 0.05


def test_platt_with_fixed_slope_fits_only_the_level():
    from survival import apply_platt, fit_platt

    rng = np.random.default_rng(4)
    z = rng.normal(0, 1, 20_000)
    y = (rng.random(z.size) < apply_platt(z, [-2.0, 1.0])).astype(int)
    a, b = fit_platt(z, y, np.ones(z.size), slope=1.0)
    assert b == 1.0 and abs(a + 2.0) < 0.1


def test_model_features_include_exclude():
    from model import model_features

    schema = {"features": ["days_in_service", "capacity_tb", "smart_5_raw", "smart_5_raw_d7",
                           "smart_9_raw", "smart_197_raw"],
              "groups": {"context": ["days_in_service", "capacity_tb"],
                         "smart": ["smart_5_raw", "smart_5_raw_d7", "smart_9_raw", "smart_197_raw"]}}
    assert model_features(schema, "all", exclude=["smart_5_*"]) == [
        "days_in_service", "capacity_tb", "smart_9_raw", "smart_197_raw"]
    assert model_features(schema, "context", include=["smart_9_raw"]) == [
        "days_in_service", "capacity_tb", "smart_9_raw"]
    with pytest.raises(ValueError, match="matches no feature"):
        model_features(schema, "all", exclude=["smart_188_*"])

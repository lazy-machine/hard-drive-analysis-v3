"""Weighted metrics against scikit-learn and brute force."""

import itertools

import numpy as np
import pytest
from sklearn.metrics import average_precision_score, roc_auc_score

from metrics import (
    bootstrap_counts, concordance, km_failure, weighted_auc, weighted_average_precision,
    weighted_quantile_threshold,
)


@pytest.fixture
def data():
    rng = np.random.default_rng(1)
    n = 500
    y = (rng.random(n) < 0.2).astype(int)
    score = np.round(rng.normal(y * 0.8, 1.0), 1)  # rounded -> plenty of ties
    w = rng.choice([1.0, 5.0, 25.0], n)
    return score, y, w


def test_auc_matches_sklearn(data):
    s, y, w = data
    assert np.isclose(weighted_auc(s, y, w), roc_auc_score(y, s, sample_weight=w))


def test_average_precision_matches_sklearn(data):
    s, y, w = data
    assert np.isclose(weighted_average_precision(s, y, w),
                      average_precision_score(y, s, sample_weight=w))


def test_auc_single_class_is_nan():
    assert np.isnan(weighted_auc(np.arange(3.0), np.ones(3), np.ones(3)))


def brute_concordance(risk, d, e, w):
    num = den = 0.0
    for i, j in itertools.permutations(range(len(d)), 2):
        if e[i] and (d[j] > d[i] or (d[j] == d[i] and not e[j])):
            pw = w[i] * w[j]
            den += pw
            num += pw * (1.0 if risk[i] > risk[j] else 0.5 if risk[i] == risk[j] else 0.0)
    return num / den


def test_concordance_matches_brute_force():
    rng = np.random.default_rng(2)
    n = 80
    d = rng.integers(0, 15, n)
    e = rng.random(n) < 0.4
    risk = np.round(-d + rng.normal(0, 4, n))
    w = rng.choice([1.0, 3.0], n)
    assert np.isclose(concordance(risk, d, e, w), brute_concordance(risk, d, e, w))


def test_km_failure_hand_computed():
    # durations/events: failures on days 2 and 5, censored at 3 and 9
    d = np.array([2, 3, 5, 9])
    e = np.array([1, 0, 1, 0])
    w = np.ones(4)
    # day 2: 1 of 4 fail -> S = 3/4. day 5: at risk {5, 9} -> 1 of 2 -> S = 3/8
    assert np.isclose(km_failure(d, e, w, 3), 1 / 4)
    assert np.isclose(km_failure(d, e, w, 6), 1 - 3 / 8)
    assert np.isclose(km_failure(d, e, w, 2), 0.0)  # "within 2 days" = days 0 and 1


def test_threshold_respects_false_alarm_budget(data):
    s, _, w = data
    t = weighted_quantile_threshold(s, w, 0.05)
    assert np.sum(w * (s >= t)) / w.sum() <= 0.05
    assert np.sum(w * (s >= np.max(s[s < t]))) / w.sum() > 0.05


def test_bootstrap_resamples_whole_drives():
    drive = np.array([0, 0, 0, 1, 1, 2])
    for counts in bootstrap_counts(drive, 3, rounds=20, seed=0):
        assert counts[0] == counts[1] == counts[2]
        assert counts[3] == counts[4]
        assert counts[[0, 3, 5]].sum() == 3


def test_quantile_calibration_counts_only_known_outcomes():
    from evaluate import quantile_calibration

    d = np.array([3, 20, 5, 40, 9])
    e = np.array([1, 1, 0, 0, 0])
    t = np.array([10.0, 10.0, 10.0, 10.0, np.inf])
    # failed before day 10: row 0. survived past it: row 3. unknown: row 2 (censored at 5),
    # row 1 failed after day 10 -> survived past it. row 4 has no finite prediction.
    share, n = quantile_calibration(d, e, np.ones(5), t)
    assert n == 3 and np.isclose(share, 1 / 3)

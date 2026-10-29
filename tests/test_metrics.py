"""Weighted metrics against scikit-learn and brute force."""

import itertools

import numpy as np
import pytest
from sklearn.metrics import average_precision_score, roc_auc_score

from metrics import (
    bootstrap_counts, bootstrap_drive_counts, censoring_survival, concordance, ipcw_weights,
    km_failure, one_per_drive, uno_concordance, weighted_auc, weighted_average_precision,
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


@pytest.fixture
def survival_data():
    rng = np.random.default_rng(3)
    n = 60
    d = rng.integers(0, 12, n)
    e = rng.random(n) < 0.4
    w = rng.choice([1.0, 3.0], n)
    risk = np.round(rng.normal(-d, 3))
    return risk, d, e, w


def brute_censoring_survival(d, e, w, t):
    """P(C >= t): product over days before t, failures leave the risk set before censoring."""
    s = 1.0
    for day in range(t):
        at_risk = w[(d > day) | ((d == day) & ~e)].sum()
        if at_risk > 0:
            s *= 1 - w[~e & (d == day)].sum() / at_risk
    return s


def test_censoring_survival_matches_brute_force(survival_data):
    _, d, e, w = survival_data
    G = censoring_survival(d, e, w)
    for t in range(14):
        assert np.isclose(G(t), brute_censoring_survival(d, e, w, t))


def test_ipcw_weights_reweight_known_rows(survival_data):
    _, d, e, w = survival_data
    H = 6
    iw = ipcw_weights(d, e, w, H)
    failed = e & (d < H)
    alive = (e & (d >= H)) | (~e & (d >= H - 1))
    assert np.all(iw[~(failed | alive)] == 0)
    for i in np.flatnonzero(failed):
        assert np.isclose(iw[i], w[i] / brute_censoring_survival(d, e, w, d[i]))
    for i in np.flatnonzero(alive):
        assert np.isclose(iw[i], w[i] / brute_censoring_survival(d, e, w, H - 1))
    # without censoring before the horizon, IPCW changes nothing
    full = np.full(d.size, 20)
    assert np.allclose(ipcw_weights(full, np.zeros(d.size, bool), w, H), w)


def test_uno_concordance_matches_brute_force(survival_data):
    risk, d, e, w = survival_data
    tau = 8
    num = den = 0.0
    for i, j in itertools.permutations(range(len(d)), 2):
        if e[i] and d[i] < tau and (d[j] > d[i] or (d[j] == d[i] and not e[j])):
            pw = w[i] / brute_censoring_survival(d, e, w, d[i]) ** 2 * w[j]
            den += pw
            num += pw * (1.0 if risk[i] > risk[j] else 0.5 if risk[i] == risk[j] else 0.0)
    assert np.isclose(uno_concordance(risk, d, e, w, tau), num / den)


def test_stratified_bootstrap_keeps_stratum_sizes():
    strata = np.array(["failing"] * 3 + ["healthy"] * 7)
    for counts in bootstrap_drive_counts(10, rounds=30, seed=1, strata=strata):
        assert counts[:3].sum() == 3 and counts[3:].sum() == 7


def test_one_per_drive_picks_each_drive_once():
    drive = np.array([2, 0, 0, 1, 2, 2, 0])
    rng = np.random.default_rng(0)
    seen = set()
    for _ in range(50):
        pick = one_per_drive(drive, rng)
        assert sorted(drive[pick]) == [0, 1, 2]
        seen |= set(pick[drive[pick] == 0])
    assert seen == {1, 2, 6}        # every row of drive 0 gets drawn sometimes


def test_one_per_drive_matches_lexsort_pick():
    """The O(n) pick returns exactly the rows the earlier lexsort version picked."""
    from metrics import one_per_drive

    def lexsort_pick(drive_index, rng):
        order = np.lexsort((rng.random(drive_index.size), drive_index))
        d = drive_index[order]
        return order[np.r_[True, d[1:] != d[:-1]]]

    for seed in range(10):
        g = np.random.default_rng(100 + seed)
        codes = g.integers(0, g.integers(1, 500), size=g.integers(1, 20000))
        assert np.array_equal(lexsort_pick(codes, np.random.default_rng(seed)),
                              one_per_drive(codes, np.random.default_rng(seed)))


def test_drive_cells_match_row_level_bootstrap():
    """A round on (tie group, drive) cells equals the metric on rows reweighted by the
    drive counts, up to floating-point rounding."""
    from metrics import DriveCells, RankedScores, weighted_auc, weighted_average_precision

    g = np.random.default_rng(3)
    n, drives = 5000, 300
    s = np.round(g.random(n), 2)            # ties
    y = (g.random(n) < 0.1).astype(int)
    codes = g.integers(0, drives, n)
    w = g.random(n)
    cells = DriveCells(RankedScores(s, y), codes, {"w": w})
    for _ in range(5):
        counts = g.integers(0, 3, drives)
        auc, ap = cells.auc_ap(counts, "w")
        wb = w * counts[codes]
        assert abs(auc - weighted_auc(s, y, wb)) < 1e-12
        assert abs(ap - weighted_average_precision(s, y, wb)) < 1e-12


def test_empty_inputs():
    from metrics import RankedScores, ap_from_groups, one_per_drive

    assert one_per_drive(np.zeros(0, dtype=np.int64), np.random.default_rng(0)).size == 0
    r = RankedScores(np.zeros(0), np.zeros(0))
    assert r.n_groups == 0 and np.isnan(r.auc(np.zeros(0)))
    assert np.isnan(ap_from_groups(np.zeros(0), np.zeros(0)))


def test_parallel_rounds_keeps_order_and_handles_zero_rounds():
    import evaluate

    assert evaluate.parallel_rounds(lambda i: i * i, 0) == []
    assert evaluate.parallel_rounds(lambda i: i * i, 7) == [i * i for i in range(7)]

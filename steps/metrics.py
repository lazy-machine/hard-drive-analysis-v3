"""Weighted evaluation metrics. Pure numpy, so they are unit-tested against brute force.

Weights are inverse sampling probabilities, so every metric estimates its value on the
real (unsampled) population of drive-days.
"""

from __future__ import annotations

import numpy as np


def _desc_order(score: np.ndarray) -> np.ndarray:
    return np.argsort(-score, kind="mergesort")


def weighted_auc(score: np.ndarray, y: np.ndarray, w: np.ndarray,
                 order: np.ndarray | None = None) -> float:
    """ROC-AUC with sample weights; ties count one half. Pass `order` to reuse a sort."""
    order = _desc_order(score) if order is None else order
    s, yy, ww = score[order], y[order].astype(bool), w[order]
    pos_w = np.where(yy, ww, 0.0)
    neg_w = np.where(yy, 0.0, ww)
    # group equal scores so ties are handled exactly
    new = np.r_[True, s[1:] != s[:-1]]
    gid = np.cumsum(new) - 1
    gp = np.bincount(gid, pos_w)
    gn = np.bincount(gid, neg_w)
    neg_above = np.cumsum(gn) - gn          # negatives with a strictly higher score
    total_p, total_n = gp.sum(), gn.sum()
    if total_p == 0 or total_n == 0:
        return float("nan")
    # each positive beats the negatives below it, and ties count one half
    wins = (gp * (total_n - neg_above - gn)).sum() + 0.5 * (gp * gn).sum()
    return float(wins / (total_p * total_n))


def weighted_average_precision(score: np.ndarray, y: np.ndarray, w: np.ndarray,
                               order: np.ndarray | None = None) -> float:
    """Area under the precision-recall curve (step-wise, like sklearn) with weights."""
    order = _desc_order(score) if order is None else order
    s, yy, ww = score[order], y[order].astype(bool), w[order]
    last = np.r_[s[1:] != s[:-1], True]               # last row of each tie group
    tp = np.cumsum(np.where(yy, ww, 0.0))[last]
    fp = np.cumsum(np.where(yy, 0.0, ww))[last]
    if tp[-1] == 0:
        return float("nan")
    precision = tp / np.maximum(tp + fp, 1e-300)
    recall = tp / tp[-1]
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def weighted_brier(p: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def km_failure(duration: np.ndarray, event: np.ndarray, w: np.ndarray, horizon: int) -> float:
    """Weighted Kaplan-Meier estimate of P(fail within horizon days), i.e. on a day < horizon.

    At-risk on day t: duration >= t (a censored drive is alive through its last day).
    """
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    days = np.unique(duration[event & (duration < horizon)])
    if days.size == 0:
        return 0.0
    order = np.argsort(duration)
    d_sorted, w_sorted = duration[order], w[order]
    total = w_sorted.sum()
    # weight with duration >= t = total - weight with duration < t
    below = np.r_[0.0, np.cumsum(w_sorted)]
    at_risk = total - below[np.searchsorted(d_sorted, days, side="left")]
    ev_w = np.bincount(np.searchsorted(days, duration[event & (duration < horizon)]),
                       w[event & (duration < horizon)], minlength=days.size)
    surv = np.prod(1.0 - ev_w / np.maximum(at_risk, 1e-300))
    return float(1.0 - surv)


def concordance(risk: np.ndarray, duration: np.ndarray, event: np.ndarray,
                w: np.ndarray) -> float:
    """Weighted Harrell's C: P(higher risk fails first) over comparable pairs.

    A pair (i, j) is comparable when i fails (event) and j is known alive longer: j's
    duration is greater, or equal with j censored. Pair weight w_i * w_j; risk ties count
    one half. O(n log n) with a Fenwick tree over risk ranks.
    """
    risk = np.asarray(risk, dtype=float)
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    ranks = np.unique(risk, return_inverse=True)[1]
    m = ranks.max() + 1 if ranks.size else 0
    tree = np.zeros(m + 1)

    def add(i: int, v: float) -> None:
        i += 1
        while i <= m:
            tree[i] += v
            i += i & -i

    def prefix(i: int) -> float:  # sum of ranks < i
        s = 0.0
        while i > 0:
            s += tree[i]
            i -= i & -i
        return s

    total_added = 0.0
    conc = disc = tie = 0.0
    order = np.lexsort((event, -duration))  # by duration desc, censored before events
    i = 0
    n = order.size
    while i < n:
        j = i
        d = duration[order[i]]
        while j < n and duration[order[j]] == d:
            j += 1
        group = order[i:j]
        cens = group[~event[group]]
        evs = group[event[group]]
        for c in cens:
            add(ranks[c], w[c])
            total_added += w[c]
        for e in evs:
            r = ranks[e]
            less = prefix(r)
            leq = prefix(r + 1)
            conc += w[e] * less
            tie += w[e] * (leq - less)
            disc += w[e] * (total_added - leq)
        for e in evs:
            add(ranks[e], w[e])
            total_added += w[e]
        i = j
    denom = conc + disc + tie
    return float((conc + 0.5 * tie) / denom) if denom > 0 else float("nan")


def weighted_quantile_threshold(score: np.ndarray, w: np.ndarray, rate: float) -> float:
    """Smallest threshold t such that the weighted share of score >= t is at most `rate`."""
    order = _desc_order(score)
    s, cw = score[order], np.cumsum(w[order]) / w.sum()
    # tie groups must be taken whole, so evaluate at the last row of each group
    last = np.r_[s[1:] != s[:-1], True]
    ok = np.flatnonzero(last & (cw <= rate))
    if ok.size == 0:
        return float(np.nextafter(s[0], np.inf))  # alert on nothing
    return float(s[ok[-1]])


def bootstrap_counts(drive_index: np.ndarray, n_drives: int, rounds: int, seed: int):
    """Yield, per round, the multiplicity of each row under a drive-level bootstrap.

    Snapshots of one drive are resampled together, because they are strongly correlated
    and treating them as independent makes intervals far too narrow.
    """
    rng = np.random.default_rng(seed)
    p = np.full(n_drives, 1.0 / n_drives)
    for _ in range(rounds):
        yield rng.multinomial(n_drives, p)[drive_index]

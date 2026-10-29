"""Weighted evaluation metrics. Pure numpy, so they are unit-tested against brute force.

Weights are inverse sampling probabilities, so every metric estimates its value on the
real (unsampled) population of drive-days.
"""

from __future__ import annotations

import numpy as np


def _desc_order(score: np.ndarray) -> np.ndarray:
    return np.argsort(-score, kind="mergesort")


def auc_from_groups(gp: np.ndarray, gn: np.ndarray) -> float:
    """Weighted ROC-AUC from positive / negative weight per tie group, groups in
    descending score order. Ties count one half."""
    neg_above = np.cumsum(gn) - gn          # negatives with a strictly higher score
    total_p, total_n = gp.sum(), gn.sum()
    if total_p == 0 or total_n == 0:
        return float("nan")
    # each positive beats the negatives below it, and ties count one half
    wins = (gp * (total_n - neg_above - gn)).sum() + 0.5 * (gp * gn).sum()
    return float(wins / (total_p * total_n))


def ap_from_groups(gp: np.ndarray, gn: np.ndarray) -> float:
    """Area under the precision-recall curve (step-wise, like sklearn) from the same
    per-group weights: one threshold per tie group."""
    tp, fp = np.cumsum(gp), np.cumsum(gn)
    if tp[-1] == 0:
        return float("nan")
    precision = tp / np.maximum(tp + fp, 1e-300)
    recall = tp / tp[-1]
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


class RankedScores:
    """A score sorted once into tie groups, for many weighted AUC / AP evaluations."""

    def __init__(self, score: np.ndarray, y: np.ndarray, order: np.ndarray | None = None):
        self.order = _desc_order(score) if order is None else order
        s = score[self.order]
        self.yy = y[self.order].astype(bool)
        # group equal scores so ties are handled exactly
        self.gid = np.cumsum(np.r_[True, s[1:] != s[:-1]]) - 1
        self.n_groups = int(self.gid[-1]) + 1 if self.gid.size else 0

    def group_weights(self, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Positive and negative weight per tie group."""
        ww = w[self.order]
        return (np.bincount(self.gid, np.where(self.yy, ww, 0.0), minlength=self.n_groups),
                np.bincount(self.gid, np.where(self.yy, 0.0, ww), minlength=self.n_groups))

    def auc(self, w: np.ndarray) -> float:
        return auc_from_groups(*self.group_weights(w))

    def average_precision(self, w: np.ndarray) -> float:
        return ap_from_groups(*self.group_weights(w))


class DriveCells:
    """A ranked score's rows collapsed into (tie group, drive) cells, for drive-level
    bootstrap rounds.

    A round only changes how often each drive is drawn, so the weight of a cell in a
    round is its summed weight times its drive's count. A round then costs O(cells)
    instead of O(rows), and there are far fewer cells than rows because a drive's
    snapshots often share a score. `weights` names the weight vectors to sum.
    """

    def __init__(self, ranked: RankedScores, codes: np.ndarray,
                 weights: dict[str, np.ndarray]):
        n_drives = int(codes.max()) + 1 if codes.size else 1
        key = ranked.gid.astype(np.int64) * n_drives + codes[ranked.order]
        cells, cell_of_row = np.unique(key, return_inverse=True)
        self.group, self.drive = cells // n_drives, cells % n_drives
        self.n_groups = ranked.n_groups
        self.pos, self.neg = {}, {}
        for name, w in weights.items():
            ww = w[ranked.order]
            self.pos[name] = np.bincount(cell_of_row, np.where(ranked.yy, ww, 0.0))
            self.neg[name] = np.bincount(cell_of_row, np.where(ranked.yy, 0.0, ww))

    def auc_ap(self, drive_counts: np.ndarray, weights: str) -> tuple[float, float]:
        """(AUC, AP) with every drive's weight multiplied by its count in the round."""
        m = drive_counts[self.drive]
        gp = np.bincount(self.group, self.pos[weights] * m, minlength=self.n_groups)
        gn = np.bincount(self.group, self.neg[weights] * m, minlength=self.n_groups)
        return auc_from_groups(gp, gn), ap_from_groups(gp, gn)


def weighted_auc(score: np.ndarray, y: np.ndarray, w: np.ndarray,
                 order: np.ndarray | None = None) -> float:
    """ROC-AUC with sample weights; ties count one half. Pass `order` to reuse a sort."""
    return RankedScores(score, y, order).auc(w)


def weighted_average_precision(score: np.ndarray, y: np.ndarray, w: np.ndarray,
                               order: np.ndarray | None = None) -> float:
    """Area under the precision-recall curve (step-wise, like sklearn) with weights."""
    return RankedScores(score, y, order).average_precision(w)


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


def _fenwick_add(tree: np.ndarray, pos: np.ndarray, v: np.ndarray) -> None:
    """Add v at 1-based positions pos, all at once."""
    pos, v = pos.copy(), v.copy()
    while pos.size:
        np.add.at(tree, pos, v)
        pos = pos + (pos & -pos)
        keep = pos < tree.size
        pos, v = pos[keep], v[keep]


def _fenwick_prefix(tree: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Sum over 1-based positions 1..pos, for every pos at once."""
    out = np.zeros(pos.size)
    pos = pos.copy()
    live = pos > 0
    while live.any():
        out[live] += tree[pos[live]]
        pos[live] -= pos[live] & -pos[live]
        live = pos > 0
    return out


def concordance(risk: np.ndarray, duration: np.ndarray, event: np.ndarray,
                w: np.ndarray, event_weight: np.ndarray | None = None) -> float:
    """Weighted Harrell's C: P(higher risk fails first) over comparable pairs.

    A pair (i, j) is comparable when i fails (event) and j is known alive longer: j's
    duration is greater, or equal with j censored. Pair weight w_i * w_j; risk ties count
    one half. O(n log n) with a Fenwick tree over risk ranks, processed one duration at a
    time (durations are whole days, so there are few distinct values).

    `event_weight` replaces w_i for the failing member of a pair (Uno's C passes
    w_i / G(T_i)^2 there, and 0 for failures past its truncation time).
    """
    risk = np.asarray(risk, dtype=float)
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    w = np.asarray(w, dtype=float)
    ew = w if event_weight is None else np.asarray(event_weight, dtype=float)
    ranks = np.unique(risk, return_inverse=True)[1] + 1      # 1-based for the tree
    m = int(ranks.max()) if ranks.size else 0
    tree = np.zeros(m + 1)
    order = np.argsort(-duration, kind="stable")             # longest durations first
    d_sorted = duration[order]
    starts = np.flatnonzero(np.r_[True, d_sorted[1:] != d_sorted[:-1]])
    ends = np.r_[starts[1:], order.size]
    total_added = conc = disc = tie = 0.0
    for a, b in zip(starts, ends, strict=True):
        group = order[a:b]
        is_ev = event[group]
        cens, evs = group[~is_ev], group[is_ev]
        if cens.size:                                        # alive at least this long
            _fenwick_add(tree, ranks[cens], w[cens])
            total_added += w[cens].sum()
        if evs.size:
            r = ranks[evs]
            less = _fenwick_prefix(tree, r - 1)
            leq = _fenwick_prefix(tree, r)
            conc += np.sum(ew[evs] * less)
            tie += np.sum(ew[evs] * (leq - less))
            disc += np.sum(ew[evs] * (total_added - leq))
            _fenwick_add(tree, r, w[evs])
            total_added += w[evs].sum()
    denom = conc + disc + tie
    return float((conc + 0.5 * tie) / denom) if denom > 0 else float("nan")


def censoring_survival(duration: np.ndarray, event: np.ndarray, w: np.ndarray):
    """Weighted Kaplan-Meier of the censoring time: a function t -> P(C >= t).

    Same day conventions as the labels: a censored row at d is observed alive through day
    d, a failure on day d is seen when C >= d. At a tie, failures come before censoring,
    so a row failing on day d is not at risk of being censored on day d.
    """
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    w = np.asarray(w, dtype=float)
    days = np.unique(duration[~event])
    order = np.argsort(duration)
    d_sorted, w_sorted = duration[order], w[order]
    below = np.r_[0.0, np.cumsum(w_sorted)]
    at_risk = w.sum() - below[np.searchsorted(d_sorted, days, side="left")]
    ev_at = np.bincount(np.searchsorted(days, duration[event & np.isin(duration, days)]),
                        w[event & np.isin(duration, days)], minlength=days.size)
    cens_w = np.bincount(np.searchsorted(days, duration[~event]), w[~event], minlength=days.size)
    G_after = np.cumprod(1.0 - cens_w / np.maximum(at_risk - ev_at, 1e-300))  # P(C > day)

    def G(t):
        """P(C >= t) = P(C > t - 1) on whole days."""
        k = np.searchsorted(days, np.asarray(t) - 1, side="right") - 1
        return np.where(k >= 0, G_after[np.maximum(k, 0)], 1.0)

    return G


def ipcw_weights(duration: np.ndarray, event: np.ndarray, w: np.ndarray, horizon: int,
                 G=None) -> np.ndarray:
    """Inverse-probability-of-censoring weights for "fails within horizon".

    Dropping rows whose status at the horizon is unknown is unbiased only if censoring is
    unrelated to risk and to follow-up length. IPCW reweights the known rows instead: a
    failure on day d by 1 / P(C >= d), a row known alive through day horizon-1 by
    1 / P(C >= horizon-1), an unknown row by 0 (Uno et al. 2011, Vock et al. 2016).
    """
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    G = censoring_survival(duration, event, w) if G is None else G
    out = np.zeros(duration.shape, dtype=float)
    failed = event & (duration < horizon)
    alive = (event & (duration >= horizon)) | (~event & (duration >= horizon - 1))
    out[failed] = w[failed] / np.maximum(G(duration[failed]), 1e-12)
    out[alive] = w[alive] / max(float(G(horizon - 1)), 1e-12)
    return out


def uno_concordance(risk, duration, event, w, tau: int, G=None) -> float:
    """Uno's C truncated at tau: Harrell's pairs, each failure weighted by 1 / G(T)^2, so
    the estimate does not depend on the censoring pattern (Uno et al. 2011)."""
    duration = np.asarray(duration)
    event = np.asarray(event, dtype=bool)
    w = np.asarray(w, dtype=float)
    G = censoring_survival(duration, event, w) if G is None else G
    g = np.maximum(G(duration), 1e-12)
    ew = np.where(event & (duration < tau), w / g**2, 0.0)
    return concordance(risk, duration, event, w, event_weight=ew)


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


def bootstrap_drive_counts(n_drives: int, rounds: int, seed: int, strata=None):
    """Yield, per round, how often each drive is drawn in a drive-level bootstrap.

    With `strata` (one label per drive), drives are resampled within each stratum, which
    keeps the stratified sample's failing/healthy mix fixed like the sampling design did.
    """
    rng = np.random.default_rng(seed)
    groups = ([np.arange(n_drives)] if strata is None else
              [np.flatnonzero(strata == s) for s in np.unique(strata)])
    for _ in range(rounds):
        counts = np.zeros(n_drives, dtype=np.int64)
        for g in groups:
            if g.size:
                counts[g] = rng.multinomial(g.size, np.full(g.size, 1.0 / g.size))
        yield counts


def bootstrap_counts(drive_index: np.ndarray, n_drives: int, rounds: int, seed: int,
                     strata=None):
    """Yield, per round, the multiplicity of each row under a drive-level bootstrap.

    Snapshots of one drive are resampled together, because they are strongly correlated
    and treating them as independent makes intervals far too narrow.
    """
    for counts in bootstrap_drive_counts(n_drives, rounds, seed, strata):
        yield counts[drive_index]


def one_per_drive(drive_index: np.ndarray, rng, grouped: np.ndarray | None = None
                  ) -> np.ndarray:
    """Row indices of one random row per drive (for drive-level metrics), in drive order.

    Each row draws a uniform number and each drive keeps its row with the smallest one.
    `grouped` (np.argsort(drive_index, kind="stable")) can be passed to reuse that sort.
    """
    r = rng.random(drive_index.size)
    grouped = np.argsort(drive_index, kind="stable") if grouped is None else grouped
    d = drive_index[grouped]
    starts = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    rs = r[grouped]
    is_min = rs == np.repeat(np.minimum.reduceat(rs, starts), np.diff(np.r_[starts, rs.size]))
    # the first minimum of each drive (ties between uniform draws do not happen in practice)
    first = np.flatnonzero(is_min)
    first = first[np.r_[True, d[first][1:] != d[first][:-1]]]
    return grouped[first]

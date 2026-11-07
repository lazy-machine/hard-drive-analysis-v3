"""tiny_scorecard: a hazard model small enough to read in one sitting.

    hazard_k(x) = sigmoid(base_k + sum of points of the rules x trips)

One risk score shared by all 7 survival bins (proportional hazards on the logit scale),
7 baseline levels, and a short list of rules of the form `smart_197_raw > 0`, each worth
some points (a logit). The harness fits a Platt slope per bin afterwards, so the score
does not need to be equally sharp in every bin.

How it is built:
  * Candidate rules are threshold indicators on a short list of physically meaningful
    counters (reallocated / pending / uncorrectable sectors, command timeouts, ...), their
    7- and 30-day changes, and a few non-monotone context features (age, temperature).
    No drive model, vendor or capacity: those drift with the fleet mix.
  * Rules are chosen greedily (forward selection). Fit rows are the early train rows
    (before 2022); each candidate is judged on the `stop` drives in 2022, so the choice
    rewards rules that still help on other drives and in a later period.
  * Counters can only raise risk (points >= 0). Age and temperature can go either way.
  * The score is learned on the bins up to 60 days, which decide the 30 and 60-day
    ranking. The baselines of the three long bins are fitted afterwards, score fixed.
  * Final points are refitted on all train rows. Everything is a weighted logistic fit on
    count tables: snapshots with the same rule profile are merged, so there is no 28M-row
    expansion and fitting takes seconds.

Saved to model_dir/scorecard.json and printed in the log.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from survival import expand, known_status

WEIGHT_POWER = 0.5
SCORE_BINS = 4              # bins 0..3 (days 0-59) shape the score
MAX_RULES = 20              # 7 baselines + 20 rules = 27 parameters at most
MIN_GAIN_EVENTS = 100.0     # a rule must gain this many "average failure rows" of log-lik on stop
SHRINK_EVENTS = 300.0       # prior curvature, in failure rows: rare rules get small points
MAX_POINTS = 4.0
SHORTLIST = 8
SPLIT_DATE = pd.Timestamp("2022-01-01")
MAX_LEVELS = 7              # thresholds per feature are capped at 6 (3 bits of key)
QUANTILES = (0.25, 0.5, 0.75, 0.9, 0.97, 0.995)

# (feature, sign, monotone). sign +1: rule is `x > t`; sign -1: rule is `x < t` (a falling
# normalised value is worse). monotone: points are constrained >= 0.
COUNTERS = ["smart_5_raw", "smart_183_raw", "smart_184_raw", "smart_187_raw", "smart_189_raw",
            "smart_196_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw", "smart_10_raw",
            "smart_192_raw"]
DELTAS = ["smart_5_raw", "smart_183_raw", "smart_187_raw", "smart_189_raw", "smart_197_raw",
          "smart_198_raw", "smart_199_raw"]
NORMALIZED = ["smart_5_normalized", "smart_187_normalized", "smart_188_normalized",
              "smart_197_normalized", "smart_198_normalized", "smart_7_normalized",
              "smart_1_normalized", "smart_3_normalized"]
CONTEXT = ["days_in_service", "smart_9_raw", "smart_194_raw"]   # free sign


def pool():
    items = [(f, +1, True) for f in COUNTERS]
    items += [(f"{f}_d{w}", +1, True) for f in DELTAS for w in (7, 30)]
    items += [(f, -1, True) for f in NORMALIZED]
    items += [(f, +1, False) for f in CONTEXT]
    return items


def sigmoid(t):
    return 0.5 * (1.0 + np.tanh(0.5 * t))


def softplus(t):
    return np.logaddexp(0.0, t)


def thresholds_for(v, monotone):
    """Candidate cut points (in the signed scale) from a sample of one feature."""
    v = v[~np.isnan(v)]
    if v.size == 0 or v.min() == v.max():
        return []
    if monotone:
        floor = 0.0 if v.min() <= 0.0 <= v.max() else v.min()
        cuts = [floor]
        above = v[v > floor]
        if above.size >= 50:
            cuts += list(np.quantile(above, QUANTILES))
    else:
        cuts = list(np.quantile(v, (0.1, 0.25, 0.5, 0.75, 0.9, 0.97)))
    cuts = [float(f"{c:.2g}") for c in cuts]            # two significant digits: readable
    cuts = sorted(set(cuts))
    # a cut must leave something on both sides
    cuts = [c for c in cuts if (v > c).any() and (v <= c).any()]
    return cuts[:MAX_LEVELS - 1]


def codes_of(X, columns, signs, cuts):
    """Ordinal level per feature: number of cut points the signed value exceeds."""
    out = np.zeros((X.shape[0], len(columns)), dtype=np.uint8)
    for j, (c, s) in enumerate(zip(columns, signs)):
        v = s * X[:, c].astype(np.float64)
        level = np.searchsorted(np.asarray(cuts[j]), v, side="left")
        out[:, j] = np.where(np.isnan(v), 0, level)
    return out


def pack(codes):
    """Rows of 3-bit codes -> two uint64 keys (21 features each)."""
    keys = []
    for lo in range(0, codes.shape[1], 21):
        k = np.zeros(codes.shape[0], dtype=np.uint64)
        for j in range(lo, min(lo + 21, codes.shape[1])):
            k = (k << np.uint64(3)) | codes[:, j].astype(np.uint64)
        keys.append(k)
    return keys


class Tables:
    """Snapshots merged by rule profile: weighted at-risk exposure n and events e per bin."""

    def __init__(self, codes, n_fit, e_fit, n_all, e_all, n_eval, e_eval):
        self.codes, self.n_fit, self.e_fit = codes, n_fit, e_fit
        self.n_all, self.e_all, self.n_eval, self.e_eval = n_all, e_all, n_eval, e_eval


def accumulate(gid, groups, part, mask, edges, chunk=400_000):
    """Per (group, bin): sum of weight*exposure and of weight*label, for rows in mask."""
    K = len(edges) - 1
    n = np.zeros(groups * K)
    e = np.zeros(groups * K)
    rows = np.flatnonzero(mask)
    meta = part.meta
    d, ev, w = (meta[c].to_numpy() for c in ("duration_days", "event", "weight"))
    for lo in range(0, rows.size, chunk):
        r = rows[lo:lo + chunk]
        idx, bins, y, ww = expand(d[r], ev[r], w[r] ** WEIGHT_POWER, edges)
        key = gid[r][idx].astype(np.int64) * K + bins
        n += np.bincount(key, weights=ww, minlength=groups * K)
        e += np.bincount(key, weights=ww * y, minlength=groups * K)
    return n.reshape(groups, K), e.reshape(groups, K)


def prepare(data, model_dir):
    t = time.time()
    names = {f: i for i, f in enumerate(data.features)}
    items = [it for it in pool() if it[0] in names]
    # cut points from a strided sample of train: binning, not model fitting
    sample = np.array(data.train.X[::max(1, data.train.X.shape[0] // 400_000)])
    cuts, kept = [], []
    for f, s, mono in items:
        c = thresholds_for(s * sample[:, names[f]].astype(np.float64), mono)
        if c:
            cuts.append(c)
            kept.append((f, s, mono))
    columns = [names[f] for f, _, _ in kept]
    signs = [s for _, s, _ in kept]

    def encode(part):
        out = np.zeros((part.X.shape[0], len(columns)), dtype=np.uint8)
        for lo in range(0, out.shape[0], 500_000):
            out[lo:lo + 500_000] = codes_of(np.array(part.X[lo:lo + 500_000]), columns, signs, cuts)
        return out

    c_tr, c_st = encode(data.train), encode(data.stop)
    allc = np.vstack([c_tr, c_st])
    k1, *rest = pack(allc)
    frame = pd.DataFrame({"a": k1, **{f"b{i}": k for i, k in enumerate(rest)}})
    gid = frame.groupby(list(frame.columns), sort=False).ngroup().to_numpy()
    groups = int(gid.max()) + 1
    first = np.full(groups, -1, dtype=np.int64)
    first[gid[::-1]] = np.arange(gid.size)[::-1]       # first row of each group
    codes = allc[first]
    g_tr, g_st = gid[:len(c_tr)], gid[len(c_tr):]
    edges = data.bin_edges
    early = (data.train.meta["date"] < SPLIT_DATE).to_numpy()
    late = (data.stop.meta["date"] >= SPLIT_DATE).to_numpy()
    n_fit, e_fit = accumulate(g_tr, groups, data.train, early, edges)
    n_all, e_all = accumulate(g_tr, groups, data.train, np.ones(len(g_tr), bool), edges)
    n_eval, e_eval = accumulate(g_st, groups, data.stop, late, edges)
    print(f"prepare: {len(kept)} candidate features, {sum(map(len, cuts))} candidate rules, "
          f"{groups} rule profiles from {len(gid)} rows, {time.time() - t:.1f}s", flush=True)
    ev = data.stop.meta[late & (data.stop.meta["event"].to_numpy() == 1)]
    unit = float(np.mean(ev["weight"].to_numpy() ** WEIGHT_POWER)) if len(ev) else 1.0
    return {"unit": unit, "features": [f for f, _, _ in kept], "signs": signs, "monotone": [m for *_, m in kept],
            "cuts": cuts, "tables": Tables(codes, n_fit, e_fit, n_all, e_all, n_eval, e_eval)}


# ---------------------------------------------------------------- fitting

def design(codes, rules):
    """Group x rule indicator matrix for rules [(feature index, level j)]: code >= j."""
    if not rules:
        return np.zeros((codes.shape[0], 0))
    return np.stack([(codes[:, f] >= j) for f, j in rules], axis=1).astype(np.float64)


def fit_points(Z, n, e, mono, lam, a0=None, b0=None):
    """Weighted logistic fit of bins 0..SCORE_BINS-1: eta = a_k + Z @ beta, beta >= 0 where mono."""
    n, e = n[:, :SCORE_BINS], e[:, :SCORE_BINS]
    scale = n.sum()
    n, e = n / scale, e / scale
    ridge = 0.5 * lam / scale
    m = Z.shape[1]

    def f(theta):
        a, b = theta[:SCORE_BINS], theta[SCORE_BINS:]
        eta = a[None, :] + (Z @ b)[:, None]
        p = sigmoid(eta)
        loss = np.sum(n * softplus(eta) - e * eta) + ridge * np.sum(b * b)
        r = n * p - e
        grad = np.concatenate([r.sum(0), Z.T @ r.sum(1) + 2 * ridge * b])
        return loss, grad

    a_init = np.log(np.maximum(e.sum(0), 1e-12) / np.maximum(n.sum(0) - e.sum(0), 1e-12)) \
        if a0 is None else a0
    theta0 = np.concatenate([a_init, np.zeros(m) if b0 is None else b0])
    bounds = [(None, None)] * SCORE_BINS + [(0.0, MAX_POINTS) if mo else (-MAX_POINTS, MAX_POINTS) for mo in mono]
    res = minimize(f, theta0, jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 300, "ftol": 1e-12, "gtol": 1e-9})
    return res.x[:SCORE_BINS], res.x[SCORE_BINS:]


def table_loss(eta, n, e):
    """Weighted log-loss in the original (unnormalised) units, bins 0..SCORE_BINS-1."""
    n, e = n[:, :SCORE_BINS], e[:, :SCORE_BINS]
    return float(np.sum(n * softplus(eta) - e * eta))


def long_baselines(s, n, e, a_short):
    """Intercepts of the remaining bins given the fixed score s (Newton on one number each)."""
    out = list(a_short)
    for k in range(SCORE_BINS, n.shape[1]):
        a = float(np.log(max(e[:, k].sum(), 1e-12) / max(n[:, k].sum() - e[:, k].sum(), 1e-12)))
        for _ in range(30):
            p = sigmoid(a + s)
            g = np.sum(n[:, k] * p - e[:, k])
            h = np.sum(n[:, k] * p * (1 - p))
            step = g / max(h, 1e-12)
            a -= step
            if abs(step) < 1e-9:
                break
        out.append(a)
    return np.array(out)


def select_rules(st, log):
    t = st["tables"]
    codes = t.codes
    F = len(st["features"])
    levels = [len(c) for c in st["cuts"]]
    mono = st["monotone"]
    chosen: list[tuple[int, int]] = []
    a = b = None
    unit = st["unit"]
    lam = SHRINK_EVENTS * unit
    eta_all = np.zeros((codes.shape[0], SCORE_BINS))
    history = []
    for step in range(MAX_RULES):
        # eta with current model, from scratch
        if chosen:
            Z = design(codes, chosen)
            eta_all = a[None, :] + (Z @ b)[:, None]
        else:
            n0, e0 = t.n_fit[:, :SCORE_BINS], t.e_fit[:, :SCORE_BINS]
            a = np.log(e0.sum(0) / (n0.sum(0) - e0.sum(0)))
            eta_all = np.repeat(a[None, :], codes.shape[0], axis=0)
        p = sigmoid(eta_all)
        nf, ef = t.n_fit[:, :SCORE_BINS], t.e_fit[:, :SCORE_BINS]
        r = (nf * p - ef).sum(1)                         # score (gradient) per profile
        h = (nf * p * (1 - p)).sum(1)
        base_eval = table_loss(eta_all, t.n_eval, t.e_eval)
        # score test for every candidate rule via tail sums over levels
        cand = []
        for f in range(F):
            L = levels[f] + 1
            gr = np.bincount(codes[:, f], weights=r, minlength=L)
            hh = np.bincount(codes[:, f], weights=h, minlength=L)
            g_tail = np.cumsum(gr[::-1])[::-1]
            h_tail = np.cumsum(hh[::-1])[::-1]
            for j in range(1, L):
                if (f, j) in chosen:
                    continue
                g_, h_ = g_tail[j], h_tail[j] + lam
                if h_ <= 0:
                    continue
                if mono[f] and g_ >= 0:
                    continue
                cand.append((g_ * g_ / (2 * h_), f, j))
        cand.sort(reverse=True)
        best = None
        for _, f, j in cand[:SHORTLIST]:
            mask = codes[:, f] >= j
            delta = 0.0
            for _ in range(25):                           # Newton on the single new point
                pp = sigmoid(eta_all[mask] + delta)
                gg = np.sum(nf[mask] * pp - ef[mask])
                hh_ = np.sum(nf[mask] * pp * (1 - pp)) + lam
                nd = (delta * hh_ - gg - lam * delta) / hh_   # Newton with a ridge on delta
                nd = min(max(nd, 0.0 if mono[f] else -MAX_POINTS), MAX_POINTS)
                if abs(nd - delta) < 1e-9:
                    delta = nd
                    break
                delta = nd
            eta_try = eta_all.copy()
            eta_try[mask] += delta
            gain = base_eval - table_loss(eta_try, t.n_eval, t.e_eval)
            if best is None or gain > best[0]:
                best = (gain, f, j, delta)
        if best is None:
            log("no candidate left")
            break
        gain, f, j, delta = best
        floor = MIN_GAIN_EVENTS * unit
        if gain < floor:
            log(f"stop: best next rule {st['features'][f]} level {j} gains {gain:.3g} "
                f"on the later stop rows, below {floor:.3g}")
            break
        chosen.append((f, j))
        Z = design(codes, chosen)
        a, b = fit_points(Z, t.n_fit, t.e_fit, [mono[f_] for f_, _ in chosen], lam)
        eta_new = a[None, :] + (Z @ b)[:, None]
        history.append((st["features"][f], j, gain, base_eval - table_loss(eta_new, t.n_eval, t.e_eval)))
        log(f"rule {len(chosen):2d}: {st['features'][f]} level>={j}  eval gain {gain:.4g} "
            f"(refit total gain so far {history[-1][3]:.4g})")
    return chosen


def fit(data, model_dir, deadline, state):
    t0 = time.time()
    log = lambda s: print(f"[fit {time.time() - t0:5.1f}s] {s}", flush=True)  # noqa: E731
    st = state
    t = st["tables"]
    chosen = select_rules(st, log)
    mono = [st["monotone"][f] for f, _ in chosen]
    # final points on all train rows
    Z = design(t.codes, chosen)
    a, b = fit_points(Z, t.n_all, t.e_all, mono, SHRINK_EVENTS * st["unit"])
    s = Z @ b if len(chosen) else np.zeros(t.codes.shape[0])
    base = long_baselines(s, t.n_all, t.e_all, a)
    rules = []
    for (f, j), pts in zip(chosen, b):
        thr = st["cuts"][f][j - 1]
        sign = st["signs"][f]
        rules.append({"feature": st["features"][f], "column": data.features.index(st["features"][f]),
                      "op": ">" if sign > 0 else "<",
                      "threshold": sign * thr, "points": float(pts)})
    # drop rules whose refit points hit zero: they are not part of the model
    live = [r for r in rules if abs(r["points"]) > 1e-6]
    model = {"edges": list(map(int, data.bin_edges)), "baseline_logit": [float(x) for x in base],
             "rules": live, "parameters": len(base) + len(live)}
    (model_dir / "scorecard.json").write_text(json.dumps(model, indent=1))
    report(model, log)
    # sanity: the saved card on the later stop rows (report only, not used for any choice)
    quick_check(data, model, log)


def report(model, log):
    log(f"scorecard: {len(model['rules'])} rules + {len(model['baseline_logit'])} baselines "
        f"= {model['parameters']} parameters")
    lo = model["edges"]
    print("\nBASELINE (logit of the hazard of a drive that trips no rule)")
    for k, b in enumerate(model["baseline_logit"]):
        print(f"  days {lo[k]:>3}-{lo[k + 1] - 1:<3}  logit {b:+.3f}  hazard {sigmoid(b):.5f}")
    print("\nRULES (add the points of every rule the drive trips; x e^points on the odds)")
    for r in sorted(model["rules"], key=lambda r: -r["points"]):
        print(f"  {r['points']:+.3f}  (x{np.exp(r['points']):6.2f})  "
              f"{r['feature']} {r['op']} {r['threshold']:g}")
    print(flush=True)


def score(model, X):
    s = np.zeros(X.shape[0])
    for r in model["rules"]:
        v = X[:, r["column"]].astype(np.float64)
        hit = (v > r["threshold"]) if r["op"] == ">" else (v < r["threshold"])   # NaN -> False
        s += r["points"] * hit
    return s


def quick_check(data, model, log):
    from sklearn.metrics import average_precision_score, roc_auc_score
    late = (data.stop.meta["date"] >= SPLIT_DATE).to_numpy()
    meta = data.stop.meta[late]
    X = np.array(data.stop.X)[late]
    s = score(model, X)
    status = known_status(meta["duration_days"].to_numpy(), meta["event"].to_numpy(), 30)
    keep = status >= 0
    y, w = status[keep], meta["weight"].to_numpy()[keep]
    if y.sum() == 0 or y.sum() == len(y):
        return
    log(f"stop 2022, 30 days (score only, harness metrics are the real ones): "
        f"ROC-AUC {roc_auc_score(y, s[keep], sample_weight=w):.3f}, "
        f"PR-AUC {average_precision_score(y, s[keep], sample_weight=w):.4f}")


def load(model_dir):
    return json.loads((model_dir / "scorecard.json").read_text())


def predict(model, X, hist):
    s = score(model, X)
    return np.asarray(model["baseline_logit"])[None, :] + s[:, None]

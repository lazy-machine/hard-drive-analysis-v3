"""Late-slice family ablation, run inside fit() at smoke scale only (it prints to the log).

Split the training drives in two halves by serial hash. Fit on the early rows (before
2021-07) of one half and score the rows from 2022 of the other half: a drive-disjoint
check that looks forward in time, as the score year does. Both orientations are averaged.
Smoke data is small and overfits fast: read directions, not sizes.
"""

from __future__ import annotations

import time
import zlib

import lightgbm as lgb
import numpy as np

from features import FAMILIES, NAMES, make_features
from survival import ExpandedSequence, expand, known_status

ROUNDS = 100
PARAMS = {"objective": "binary", "verbosity": -1, "deterministic": True, "force_row_wise": True,
          "seed": 42, "learning_rate": 0.06, "num_leaves": 31, "min_child_samples": 100,
          "feature_fraction": 0.5, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 5.0}


def _ap(score, y, w):
    o = np.argsort(-score, kind="stable")
    y, w = y[o], w[o]
    tp, fp = np.cumsum(w * y), np.cumsum(w * (1 - y))
    return float(np.sum(tp / (tp + fp) * w * y) / np.sum(w * y))


def _roc(score, y):
    from scipy.stats import rankdata
    r = rankdata(score)
    pos = y.sum()
    return float((r[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (len(y) - pos)))


def run(data, threads, deadline, categorical_idx):
    part, edges = data.train, list(data.bin_edges)
    meta = part.meta
    F = make_features(np.array(part.X), part.hist)
    n_base = F.shape[1] - len(NAMES)
    names = list(data.features) + NAMES
    group = np.array([zlib.crc32(s.encode()) % 2 for s in meta.serial_number])
    date = meta.date.to_numpy()
    folds = []
    for g in (0, 1):
        tr = (group == g) & (date < np.datetime64("2021-07-01"))
        ev = (group != g) & (date >= np.datetime64("2022-01-01"))
        ks = known_status(meta.duration_days.to_numpy()[ev], meta.event.to_numpy()[ev], 30)
        ok = ks >= 0
        folds.append((tr, np.flatnonzero(ev)[ok], ks[ok].astype(float),
                      meta.weight.to_numpy()[ev][ok]))
    print(f"[ablation] folds: train rows {[int(f[0].sum()) for f in folds]}, eval rows "
          f"{[len(f[1]) for f in folds]}, eval failures {[int(f[2].sum()) for f in folds]}",
          flush=True)

    def score(cols):
        out = []
        for tr, ev, y, w in folds:
            d = meta[tr]
            idx, bins, yy, ww = expand(d.duration_days.to_numpy(), d.event.to_numpy(),
                                       d.weight.to_numpy(), edges)
            cat = [cols.index(c) for c in categorical_idx if c in cols]
            ds = lgb.Dataset(ExpandedSequence(F[tr][:, cols], idx, np.asarray(edges)[bins]),
                             label=yy, weight=ww ** 0.5, categorical_feature=cat,
                             params={**PARAMS, "num_threads": threads})
            booster = lgb.train({**PARAMS, "num_threads": threads}, ds, ROUNDS)
            Ev = F[ev][:, cols]
            surv = np.ones(len(Ev))
            for k in range(3):                       # 30 days = first three bins
                z = booster.predict(np.hstack([Ev, np.full((len(Ev), 1), edges[k],
                                                            np.float32)]), raw_score=True)
                surv *= 1 - 1 / (1 + np.exp(-z))
            out.append((_ap(1 - surv, y, w), _roc(1 - surv, y)))
        return np.mean(out, axis=0)

    base = list(range(n_base))
    index = {n: i for i, n in enumerate(names)}
    fam = {f: [index[n] for n in ns] for f, ns in FAMILIES.items()}
    everything = list(range(len(names)))
    configs = [("base only", base), ("base + all", everything)]
    configs += [(f"base + {f}", base + c) for f, c in fam.items()]
    configs += [(f"all - {f}", [i for i in everything if i not in set(c)])
                for f, c in fam.items()]
    print("[ablation] config | cols | late AP@30 | late ROC@30 | seconds", flush=True)
    for label, cols in configs:
        if time.time() > deadline:
            print(f"[ablation] stopped at the deadline before '{label}'", flush=True)
            break
        t = time.time()
        ap, roc = score(cols)
        print(f"[ablation] {label:28s} {len(cols):4d} {ap:.4f} {roc:.4f} "
              f"{time.time() - t:5.1f}s", flush=True)

# Can SMART data predict when a hard drive will fail?

The run itself (scale, cohort, test set, gate) and the headline numbers are in [results.md](results.md). This file explains them and holds the detailed tables.

## Answer

- **Do SMART metrics carry failure information?** Yes. Adding SMART to what is known without it (drive model, capacity, time in service) improves ROC-AUC at 5 of 5 horizons with a 95% interval that excludes zero:
  - 7 days: +0.301 [0.283, 0.315]
  - 30 days: +0.275 [0.263, 0.290]
  - 90 days: +0.245 [0.229, 0.262]
  - 180 days: +0.224 [0.212, 0.238]
  - 365 days: +0.214 [0.198, 0.231]
- **How much of that is the replacement policy?** Backblaze replaces drives when counters 5, 187, 188, 197 or 198 rise, so those counters partly define the failure label. The full model's ROC-AUC exceeds the model without them by +0.101 [0.093, 0.110] at 30 days (an interval above zero at 5 of 5 horizons). The SMART gain above is therefore an upper bound on what SMART adds beyond the operator's replacement policy.
- **How far ahead?** Ranking is strongest close to failure (ROC-AUC 0.907 for 7 days) and weaker for the long term (0.789 for 365 days; long horizons are measured on earlier test snapshots, see Discrimination by horizon).
- **But failures are rare.** Even within 7 days only 0.027% of drive-days fail. The model's PR-AUC there is 0.0729 (a random ranking would score about the base rate), so at any useful recall many alerts are false (see Early warning).
- **Is it more than the last days?** Counting as positives only snapshots >= 7 days before failure, the 30-day PR-AUC is 0.0824 [0.0693, 0.0983] against 0.1301 overall (base rate 0.093% vs 0.121%); ROC-AUC 0.870 [0.860, 0.880]. Much of the precision comes from the last days before failure.
- **Silent failures** (no critical counter above zero in any test snapshot): 368 of the 1784 failing test drives. On them the 30-day ROC-AUC of survival model, SMART + context is 0.645 [0.616, 0.673] against 0.879 [0.869, 0.887] overall: still above chance.
- **When will it probably fail?** When the model names a day within the next year, it is about right on average: 6.6% of drives failed by their predicted 10% day, 37.2% by the predicted median and 81.9% by the predicted 90% day (targets 10/50/90%). For drives that do fail within a year it names a median within a year only 16.6% of the time: most failures are not visible in SMART long in advance. For healthy drives it says "more than a year" 99.8% of the time.
- **One survival model or a dedicated 30-day classifier?** At 30 days the survival model's ROC-AUC minus the classifier's is -0.000 [-0.003, 0.003] (paired bootstrap), PR-AUC +0.0145 [0.0041, 0.0244]; the survival model is not better in 56% of rounds. Neither ranks clearly better, and the survival model also covers the other horizons.
- **Against the classic rule** (log-sum of the reallocated, reported-uncorrectable, pending and offline-uncorrectable sector counters 5, 187, 197, 198), the model gains +0.055 ROC-AUC [0.047, 0.062] at 7 days.

## Discrimination by horizon

ROC-AUC and PR-AUC per drive-day snapshot, on test snapshots whose status at the horizon is known, weighted to real prevalence. Brackets: 95% drive-level bootstrap (200 rounds). Base rate = real share of drive-days that fail within the horizon. All 1784 failing test drives are positive at every horizon (each has snapshots close to its failure day), so the last column counts positive snapshots instead.

| horizon | model | ROC-AUC | PR-AUC | Brier | base rate | positive snapshots |
|---|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.907 [0.897, 0.916] | 0.0729 [0.0615, 0.0859] | 0.00027 | 0.027% | 11632 |
| 7 d | survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.0004 [0.0004, 0.0004] | 0.00027 | 0.027% | 11632 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0295 [0.0225, 0.0400] | n/a | 0.027% | 11632 |
| 30 d | survival model, SMART + context | 0.879 [0.869, 0.887] | 0.1301 [0.1102, 0.1515] | 0.00115 | 0.121% | 50334 |
| 30 d | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.00121 | 0.121% | 50334 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.879 [0.868, 0.886] | 0.1156 [0.0975, 0.1353] | 0.00126 | 0.121% | 50334 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | n/a | 0.121% | 50334 |
| 90 d | survival model, SMART + context | 0.846 [0.836, 0.858] | 0.1853 [0.1625, 0.2128] | 0.00354 | 0.388% | 145601 |
| 90 d | survival model, context only (no SMART) | 0.601 [0.586, 0.616] | 0.0054 [0.0050, 0.0058] | 0.00389 | 0.388% | 145601 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.786 [0.776, 0.798] | 0.0893 [0.0733, 0.1164] | n/a | 0.388% | 145601 |
| 180 d | survival model, SMART + context | 0.818 [0.807, 0.829] | 0.2201 [0.1961, 0.2497] | 0.00762 | 0.865% | 163747 |
| 180 d | survival model, context only (no SMART) | 0.593 [0.580, 0.605] | 0.0117 [0.0110, 0.0125] | 0.00865 | 0.865% | 163747 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.755 [0.744, 0.764] | 0.1295 [0.1095, 0.1524] | n/a | 0.865% | 163747 |
| 365 d | survival model, SMART + context | 0.789 [0.778, 0.802] | 0.3128 [0.2885, 0.3393] | 0.01826 | 2.272% | 189708 |
| 365 d | survival model, context only (no SMART) | 0.574 [0.560, 0.591] | 0.0305 [0.0280, 0.0340] | 0.02230 | 2.272% | 189708 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.722 [0.711, 0.732] | 0.2145 [0.1873, 0.2420] | n/a | 2.272% | 189708 |

A horizon of H days needs H days of follow-up to know that a drive survived it, so the longer the horizon, the earlier the test snapshots it can use. The 365-day row uses only snapshots from roughly the first test year (2024); longer horizons are measured on an earlier, different calendar cohort than the short ones, so the rows are not a like-for-like trend. Test snapshots with a known status (825321 in total): 7 d: 819135 snapshots, known-healthy ones dated up to 2025-12-25; 30 d: 795715 snapshots, known-healthy ones dated up to 2025-12-02; 90 d: 735702 snapshots, known-healthy ones dated up to 2025-10-03; 180 d: 650242 snapshots, known-healthy ones dated up to 2025-07-05; 365 d: 485740 snapshots, known-healthy ones dated up to 2025-01-01.

**Robustness.** The same ranking with inverse-probability-of-censoring weights (IPCW: snapshots whose status is unknown are represented by weighting up comparable known ones, instead of being dropped), and a drive-level ROC-AUC on one random snapshot per drive, weighted per drive (so drives with many snapshots do not dominate). Brier skill = 1 - Brier / Brier of always predicting the base rate; above 0 beats that constant.

| horizon | model | ROC-AUC, IPCW (per drive-day) | PR-AUC, IPCW (per drive-day) | ROC-AUC (per drive) | Brier skill |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.907 [0.897, 0.916] | 0.0726 [0.0611, 0.0855] | 0.906 [0.845, 0.942] | 0.008 |
| 7 d | survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.0004 [0.0004, 0.0004] | 0.632 [0.578, 0.680] | -0.000 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0294 [0.0224, 0.0399] | 0.827 [0.763, 0.866] | n/a |
| 30 d | survival model, SMART + context | 0.878 [0.868, 0.887] | 0.1271 [0.1076, 0.1484] | 0.864 [0.843, 0.889] | 0.042 |
| 30 d | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.626 [0.597, 0.650] | -0.002 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.879 [0.868, 0.886] | 0.1128 [0.0950, 0.1323] | 0.864 [0.839, 0.887] | -0.041 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0509 [0.0399, 0.0705] | 0.811 [0.785, 0.836] | n/a |
| 90 d | survival model, SMART + context | 0.845 [0.835, 0.856] | 0.1733 [0.1511, 0.1998] | 0.836 [0.822, 0.853] | 0.084 |
| 90 d | survival model, context only (no SMART) | 0.601 [0.586, 0.616] | 0.0050 [0.0047, 0.0054] | 0.624 [0.608, 0.643] | -0.007 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.774, 0.797] | 0.0825 [0.0675, 0.1088] | 0.782 [0.768, 0.799] | n/a |
| 180 d | survival model, SMART + context | 0.814 [0.804, 0.826] | 0.1900 [0.1674, 0.2187] | 0.836 [0.822, 0.851] | 0.112 |
| 180 d | survival model, context only (no SMART) | 0.593 [0.580, 0.605] | 0.0099 [0.0092, 0.0105] | 0.626 [0.610, 0.639] | -0.008 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.751 [0.740, 0.760] | 0.1094 [0.0915, 0.1308] | 0.778 [0.764, 0.791] | n/a |
| 365 d | survival model, SMART + context | 0.778 [0.767, 0.792] | 0.2313 [0.2090, 0.2588] | 0.833 [0.819, 0.848] | 0.178 |
| 365 d | survival model, context only (no SMART) | 0.575 [0.561, 0.593] | 0.0191 [0.0177, 0.0216] | 0.599 [0.585, 0.616] | -0.004 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.710 [0.699, 0.720] | 0.1497 [0.1253, 0.1765] | 0.768 [0.755, 0.781] | n/a |

[Archived figure: AUC by horizon](https://github.com/lazy-machine/hard-drive-analysis-v3/blob/2dc47742252d827c7ce3c5927efa19dc95424bcc/results/full-2026-11-09/report/auc_by_horizon.png)

## Ablations and sensitivity

Each variant against the reference (survival model, SMART + context). Gain = reference minus variant, paired on the same bootstrap rounds; "not better" = share of rounds where the reference's ROC-AUC is not higher.

- **survival model, SMART without counters 5/187/188/197/198**: drops counters 5, 187, 188, 197 and 198 (raw, normalized and trends), the ones behind Backblaze's own replacement decisions. A drive replaced because these counters rose is recorded as failed, so part of the full model's SMART signal may be the replacement policy itself; the full model's gain over context only is an upper bound on what SMART adds beyond that policy.
- **survival model, context + usage counters**: context plus the usage counters only (4, 9, 12, 193, 240-242: power-on hours, start/stop and power cycles, load cycles, head flying hours, LBAs written and read). Tests whether SMART helps only because it measures age and wear.
- **survival model, SMART + context, weight power 0.75**: the reference features with training weights to the power 0.75 instead of 0.5. Tests how much the ranking depends on the weight exponent.
- **survival model, SMART + context, weight power 1.0**: the same with the full inverse-probability weights (power 1.0).
- **survival model, SMART + context, recalibrated on the last year**: the reference trees with probabilities recalibrated on the last validation year before the training cutoff. Tests whether a recent recalibration fixes drift (see Calibration over time); the trees are the same, so ranking changes only through the per-bin recalibration.

| horizon | model | ROC-AUC | reference gain, ROC-AUC | reference gain, PR-AUC | not better |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context (reference) | 0.907 [0.897, 0.916] |  |  |  |
| 7 d | survival model, SMART without counters 5/187/188/197/198 | 0.806 [0.795, 0.819] | +0.101 [0.091, 0.109] | +0.0482 [0.0372, 0.0596] | 0% |
| 7 d | survival model, context + usage counters | 0.654 [0.639, 0.667] | +0.253 [0.239, 0.266] | +0.0723 [0.0608, 0.0852] | 0% |
| 7 d | survival model, SMART + context, weight power 0.75 | 0.904 [0.895, 0.913] | +0.003 [0.000, 0.006] | +0.0038 [-0.0011, 0.0097] | 2% |
| 7 d | survival model, SMART + context, weight power 1.0 | 0.903 [0.893, 0.912] | +0.004 [0.001, 0.007] | +0.0135 [0.0073, 0.0184] | 0% |
| 7 d | survival model, SMART + context, recalibrated on the last year | 0.907 [0.897, 0.916] | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] | 100% |
| 30 d | survival model, SMART + context (reference) | 0.879 [0.869, 0.887] |  |  |  |
| 30 d | survival model, SMART without counters 5/187/188/197/198 | 0.777 [0.765, 0.792] | +0.101 [0.093, 0.110] | +0.0883 [0.0640, 0.1049] | 0% |
| 30 d | survival model, context + usage counters | 0.654 [0.641, 0.667] | +0.225 [0.213, 0.238] | +0.1278 [0.1080, 0.1492] | 0% |
| 30 d | survival model, SMART + context, weight power 0.75 | 0.878 [0.868, 0.887] | +0.001 [-0.002, 0.003] | +0.0090 [0.0023, 0.0142] | 42% |
| 30 d | survival model, SMART + context, weight power 1.0 | 0.877 [0.865, 0.886] | +0.002 [-0.001, 0.005] | +0.0158 [0.0073, 0.0240] | 12% |
| 30 d | survival model, SMART + context, recalibrated on the last year | 0.879 [0.869, 0.887] | -0.000 [-0.000, -0.000] | -0.0000 [-0.0000, 0.0000] | 100% |
| 90 d | survival model, SMART + context (reference) | 0.846 [0.836, 0.858] |  |  |  |
| 90 d | survival model, SMART without counters 5/187/188/197/198 | 0.752 [0.737, 0.764] | +0.094 [0.087, 0.105] | +0.1289 [0.1054, 0.1567] | 0% |
| 90 d | survival model, context + usage counters | 0.654 [0.641, 0.667] | +0.192 [0.181, 0.207] | +0.1779 [0.1551, 0.2048] | 0% |
| 90 d | survival model, SMART + context, weight power 0.75 | 0.843 [0.831, 0.854] | +0.004 [0.000, 0.007] | +0.0132 [0.0071, 0.0183] | 2% |
| 90 d | survival model, SMART + context, weight power 1.0 | 0.846 [0.834, 0.857] | +0.001 [-0.003, 0.005] | +0.0150 [0.0055, 0.0244] | 38% |
| 90 d | survival model, SMART + context, recalibrated on the last year | 0.846 [0.836, 0.858] | +0.000 [0.000, 0.000] | +0.0007 [0.0003, 0.0010] | 2% |
| 180 d | survival model, SMART + context (reference) | 0.818 [0.807, 0.829] |  |  |  |
| 180 d | survival model, SMART without counters 5/187/188/197/198 | 0.726 [0.713, 0.738] | +0.092 [0.082, 0.101] | +0.1449 [0.1209, 0.1700] | 0% |
| 180 d | survival model, context + usage counters | 0.653 [0.638, 0.665] | +0.165 [0.154, 0.179] | +0.2037 [0.1801, 0.2333] | 0% |
| 180 d | survival model, SMART + context, weight power 0.75 | 0.810 [0.798, 0.824] | +0.007 [0.003, 0.012] | +0.0147 [0.0068, 0.0214] | 0% |
| 180 d | survival model, SMART + context, weight power 1.0 | 0.809 [0.799, 0.821] | +0.008 [0.003, 0.013] | +0.0290 [0.0158, 0.0420] | 0% |
| 180 d | survival model, SMART + context, recalibrated on the last year | 0.818 [0.807, 0.829] | -0.000 [-0.000, -0.000] | +0.0004 [0.0002, 0.0006] | 100% |
| 365 d | survival model, SMART + context (reference) | 0.789 [0.778, 0.802] |  |  |  |
| 365 d | survival model, SMART without counters 5/187/188/197/198 | 0.707 [0.694, 0.723] | +0.082 [0.073, 0.091] | +0.1804 [0.1552, 0.2021] | 0% |
| 365 d | survival model, context + usage counters | 0.651 [0.638, 0.666] | +0.138 [0.127, 0.149] | +0.2680 [0.2424, 0.2934] | 0% |
| 365 d | survival model, SMART + context, weight power 0.75 | 0.781 [0.769, 0.795] | +0.007 [0.003, 0.013] | +0.0100 [0.0024, 0.0189] | 0% |
| 365 d | survival model, SMART + context, weight power 1.0 | 0.783 [0.773, 0.796] | +0.006 [0.001, 0.011] | +0.0346 [0.0149, 0.0518] | 2% |
| 365 d | survival model, SMART + context, recalibrated on the last year | 0.789 [0.779, 0.803] | -0.000 [-0.001, -0.000] | -0.0008 [-0.0016, -0.0000] | 100% |

## Where the signal comes from

The ranking metrics on parts of the test set, per drive-day snapshot. Positive-side slices (lead time, silent or not) keep every known-healthy snapshot and restrict the failing ones, so their base rate is lower; population slices (vendor, capacity, entry date) restrict both. "Silent" failures are drives that fail with none of the critical counters (5, 187, 197, 198) above zero in any test snapshot. At 30 days:

| slice | model | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| all test snapshots | survival model, SMART + context | 0.879 [0.869, 0.887] | 0.1301 [0.1102, 0.1515] | 0.121% | 1784 |
| all test snapshots | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.121% | 1784 |
| all test snapshots | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | 0.121% | 1784 |
| positives >= 7 days before failure | survival model, SMART + context | 0.870 [0.860, 0.880] | 0.0824 [0.0693, 0.0983] | 0.093% | 1755 |
| positives >= 7 days before failure | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0013 [0.0012, 0.0015] | 0.093% | 1755 |
| positives >= 7 days before failure | rule: critical SMART counters (5, 187, 197, 198) | 0.814 [0.804, 0.825] | 0.0333 [0.0259, 0.0485] | 0.093% | 1755 |
| silent failures (no critical counter above zero) | survival model, SMART + context | 0.645 [0.616, 0.673] | 0.0007 [0.0004, 0.0011] | 0.025% | 368 |
| silent failures (no critical counter above zero) | survival model, context only (no SMART) | 0.549 [0.516, 0.580] | 0.0003 [0.0003, 0.0003] | 0.025% | 368 |
| silent failures (no critical counter above zero) | rule: critical SMART counters (5, 187, 197, 198) | 0.473 [0.470, 0.475] | 0.0002 [0.0002, 0.0003] | 0.025% | 368 |
| failures with a critical counter above zero | survival model, SMART + context | 0.939 [0.932, 0.947] | 0.1580 [0.1345, 0.1846] | 0.096% | 1416 |
| failures with a critical counter above zero | survival model, context only (no SMART) | 0.618 [0.602, 0.634] | 0.0015 [0.0014, 0.0017] | 0.096% | 1416 |
| failures with a critical counter above zero | rule: critical SMART counters (5, 187, 197, 198) | 0.915 [0.907, 0.922] | 0.0653 [0.0519, 0.0892] | 0.096% | 1416 |
| vendor HGST | survival model, SMART + context | 0.924 [0.907, 0.940] | 0.0848 [0.0631, 0.1211] | 0.235% | 380 |
| vendor HGST | survival model, context only (no SMART) | 0.612 [0.583, 0.643] | 0.0033 [0.0029, 0.0040] | 0.235% | 380 |
| vendor HGST | rule: critical SMART counters (5, 187, 197, 198) | 0.888 [0.870, 0.908] | 0.0436 [0.0317, 0.0727] | 0.235% | 380 |
| vendor Seagate | survival model, SMART + context | 0.900 [0.887, 0.913] | 0.1886 [0.1579, 0.2243] | 0.139% | 764 |
| vendor Seagate | survival model, context only (no SMART) | 0.614 [0.592, 0.637] | 0.0022 [0.0020, 0.0026] | 0.139% | 764 |
| vendor Seagate | rule: critical SMART counters (5, 187, 197, 198) | 0.852 [0.837, 0.868] | 0.0881 [0.0659, 0.1332] | 0.139% | 764 |
| vendor Toshiba | survival model, SMART + context | 0.782 [0.753, 0.807] | 0.1103 [0.0911, 0.1368] | 0.104% | 485 |
| vendor Toshiba | survival model, context only (no SMART) | 0.513 [0.485, 0.535] | 0.0011 [0.0009, 0.0022] | 0.104% | 485 |
| vendor Toshiba | rule: critical SMART counters (5, 187, 197, 198) | 0.740 [0.716, 0.760] | 0.0674 [0.0516, 0.0973] | 0.104% | 485 |
| vendor WDC | survival model, SMART + context | 0.831 [0.789, 0.879] | 0.0544 [0.0325, 0.0978] | 0.054% | 155 |
| vendor WDC | survival model, context only (no SMART) | 0.543 [0.500, 0.586] | 0.0007 [0.0005, 0.0025] | 0.054% | 155 |
| vendor WDC | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.751, 0.823] | 0.0427 [0.0280, 0.0775] | 0.054% | 155 |
| capacity >= 16 TB | survival model, SMART + context | 0.821 [0.799, 0.841] | 0.0758 [0.0554, 0.1032] | 0.075% | 530 |
| capacity >= 16 TB | survival model, context only (no SMART) | 0.585 [0.561, 0.615] | 0.0011 [0.0009, 0.0013] | 0.075% | 530 |
| capacity >= 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.754 [0.733, 0.773] | 0.0396 [0.0293, 0.0645] | 0.075% | 530 |
| capacity < 16 TB | survival model, SMART + context | 0.902 [0.891, 0.912] | 0.1544 [0.1297, 0.1831] | 0.165% | 1254 |
| capacity < 16 TB | survival model, context only (no SMART) | 0.531 [0.514, 0.546] | 0.0020 [0.0018, 0.0023] | 0.165% | 1254 |
| capacity < 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.850 [0.838, 0.863] | 0.0591 [0.0453, 0.0873] | 0.165% | 1254 |
| in service before the panel starts | survival model, SMART + context | 0.908 [0.319, 0.985] | 0.1609 [0.0001, 0.8890] | 0.100% | 5 |
| in service before the panel starts | survival model, context only (no SMART) | 0.637 [0.293, 0.980] | 0.0142 [0.0001, 0.1640] | 0.100% | 5 |
| in service before the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.482 [0.447, 0.611] | 0.0010 [0.0001, 0.0024] | 0.100% | 5 |
| first seen after the panel starts | survival model, SMART + context | 0.879 [0.869, 0.888] | 0.1303 [0.1105, 0.1521] | 0.121% | 1779 |
| first seen after the panel starts | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.121% | 1779 |
| first seen after the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.824 [0.814, 0.833] | 0.0522 [0.0410, 0.0721] | 0.121% | 1779 |

The same two slices for survival model, SMART + context across horizons:

| slice | horizon | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| silent failures (no critical counter above zero) | 7 d | 0.662 [0.632, 0.691] | 0.0002 [0.0001, 0.0003] | 0.006% | 368 |
| silent failures (no critical counter above zero) | 30 d | 0.645 [0.616, 0.673] | 0.0007 [0.0004, 0.0011] | 0.025% | 368 |
| silent failures (no critical counter above zero) | 90 d | 0.627 [0.596, 0.654] | 0.0018 [0.0013, 0.0032] | 0.078% | 368 |
| silent failures (no critical counter above zero) | 180 d | 0.603 [0.575, 0.636] | 0.0035 [0.0027, 0.0055] | 0.172% | 368 |
| silent failures (no critical counter above zero) | 365 d | 0.576 [0.550, 0.615] | 0.0076 [0.0061, 0.0103] | 0.452% | 368 |
| positives >= 7 days before failure | 30 d | 0.870 [0.860, 0.880] | 0.0824 [0.0693, 0.0983] | 0.093% | 1755 |
| positives >= 7 days before failure | 90 d | 0.841 [0.830, 0.853] | 0.1562 [0.1347, 0.1807] | 0.357% | 1757 |
| positives >= 7 days before failure | 180 d | 0.814 [0.803, 0.825] | 0.1995 [0.1762, 0.2284] | 0.829% | 1758 |
| positives >= 7 days before failure | 365 d | 0.786 [0.775, 0.800] | 0.2986 [0.2743, 0.3257] | 2.215% | 1758 |

## Ranking over the whole future (concordance)

Concordance between each model's risk score and the actual time to failure; 0.5 = random. Harrell's C counts the comparable pairs (the earlier time is a failure) where the riskier snapshot fails first. Uno's C weights each pair by the inverse probability of staying uncensored, so it does not depend on how much follow-up the test period allows, and is truncated at 365 days. Computed on 299930 test snapshots of 3267 drives (drives sampled whole up to a row cap). Score: -rmst_days = minus the expected days survived within a year; p30 = predicted 30-day risk, so hazard models can be compared with the classifier on the same kind of score. Intervals only on each model's main score.

| model | score | Harrell's C | Uno's C |
|---|---|---|---|
| survival model, SMART + context | -rmst_days | 0.771 [0.751, 0.789] | 0.767 [0.746, 0.784] |
| survival model, SMART + context | p30 | 0.780 | 0.776 |
| survival model, context only (no SMART) | -rmst_days | 0.583 [0.559, 0.603] | 0.585 [0.559, 0.606] |
| survival model, context only (no SMART) | p30 | 0.597 | 0.599 |
| 30-day yes/no classifier (SMART + context) | p30 | 0.782 [0.767, 0.798] | 0.778 [0.762, 0.798] |
| rule: critical SMART counters (5, 187, 197, 198) | score | 0.717 [0.698, 0.730] | 0.709 [0.689, 0.723] |
| survival model, SMART without counters 5/187/188/197/198 | -rmst_days | 0.681 [0.658, 0.707] | 0.676 [0.653, 0.704] |
| survival model, SMART without counters 5/187/188/197/198 | p30 | 0.694 | 0.690 |
| survival model, context + usage counters | -rmst_days | 0.625 [0.602, 0.648] | 0.626 [0.603, 0.649] |
| survival model, context + usage counters | p30 | 0.632 | 0.633 |
| survival model, SMART + context, weight power 0.75 | -rmst_days | 0.761 [0.736, 0.778] | 0.754 [0.729, 0.772] |
| survival model, SMART + context, weight power 0.75 | p30 | 0.778 | 0.773 |
| survival model, SMART + context, weight power 1.0 | -rmst_days | 0.759 [0.738, 0.775] | 0.752 [0.730, 0.769] |
| survival model, SMART + context, weight power 1.0 | p30 | 0.776 | 0.770 |
| survival model, SMART + context, recalibrated on the last year | -rmst_days | 0.772 [0.752, 0.789] | 0.767 [0.747, 0.784] |
| survival model, SMART + context, recalibrated on the last year | p30 | 0.780 | 0.776 |

## When will it fail? Remaining-life estimates

From each snapshot the survival model gives a curve: the day by which the failure probability reaches 10%, 50% (the median remaining life) and 90%. Beyond 365 days the model has no bins, so the answer is "more than a year". For 0.5% of all test snapshots the predicted median of survival model, SMART + context is within a year; otherwise the answer is "more than a year".

**Are the predicted days right?** Among snapshots whose predicted day falls within a year, the share that actually failed by that day should be close to the target:

| model | failed by predicted 10% day | failed by predicted median | failed by predicted 90% day |
|---|---|---|---|
| survival model, SMART + context | 6.6% (target 10%, 115829 snapshots) | 37.2% (target 50%, 48520 snapshots) | 81.9% (target 90%, 9897 snapshots) |
| survival model, context only (no SMART) | 2.8% (target 10%, 7216 snapshots) | n/a (target 50%, 0 snapshots) | n/a (target 90%, 0 snapshots) |
| survival model, SMART without counters 5/187/188/197/198 | 6.2% (target 10%, 53560 snapshots) | 27.4% (target 50%, 9557 snapshots) | 23.5% (target 90%, 2324 snapshots) |
| survival model, context + usage counters | 3.5% (target 10%, 18024 snapshots) | 6.4% (target 50%, 99 snapshots) | n/a (target 90%, 0 snapshots) |
| survival model, SMART + context, weight power 0.75 | 6.6% (target 10%, 114098 snapshots) | 30.4% (target 50%, 51058 snapshots) | 73.5% (target 90%, 12220 snapshots) |
| survival model, SMART + context, weight power 1.0 | 7.1% (target 10%, 107815 snapshots) | 31.2% (target 50%, 45393 snapshots) | 45.5% (target 90%, 12804 snapshots) |
| survival model, SMART + context, recalibrated on the last year | 5.7% (target 10%, 117843 snapshots) | 32.9% (target 50%, 51785 snapshots) | 75.0% (target 90%, 12103 snapshots) |

**How early is a failure visible?** Snapshots of drives that do fail within a year, by how far away the failure actually was. A median within a year means the model already expects the drive to die within a year. The absolute error is over the failing snapshots whose median is within a year (count in brackets):

| model | failing snapshots: median within a year | abs. error of median (days) | all test snapshots: median within a year | healthy snapshots: median beyond a year |
|---|---|---|---|---|
| survival model, SMART + context | 16.6% | 109 (46981 snapshots) | 0.5% | 99.8% |
| survival model, context only (no SMART) | 0.0% | n/a (0 snapshots) | 0.0% | 100.0% |
| survival model, SMART without counters 5/187/188/197/198 | 3.0% | 112 (9183 snapshots) | 0.1% | 100.0% |
| survival model, context + usage counters | 0.0% | 169 (82 snapshots) | 0.0% | 100.0% |
| survival model, SMART + context, weight power 0.75 | 17.5% | 103 (48944 snapshots) | 0.6% | 99.7% |
| survival model, SMART + context, weight power 1.0 | 15.4% | 101 (43648 snapshots) | 0.5% | 99.8% |
| survival model, SMART + context, recalibrated on the last year | 17.8% | 100 (49956 snapshots) | 0.6% | 99.8% |

By actual time to failure (survival model, SMART + context). Shares are of the failing drives' snapshots in each bucket:

| actual days to failure | snapshots | median predicted within a year | median of predicted median (days) |
|---|---|---|---|
| 0-6 | 11632 | 47.5% | > 1 year |
| 7-13 | 11720 | 39.9% | > 1 year |
| 14-29 | 26982 | 34.4% | > 1 year |
| 30-59 | 48813 | 26.6% | > 1 year |
| 60-89 | 46454 | 21.1% | > 1 year |
| 90-179 | 18146 | 14.4% | > 1 year |
| 180-364 | 25961 | 8.2% | > 1 year |

[Archived figure: remaining life](https://github.com/lazy-machine/hard-drive-analysis-v3/blob/2dc47742252d827c7ce3c5927efa19dc95424bcc/results/full-2026-11-09/report/remaining_life.png)

## Early warning

Each alert threshold is set on validation drives so that a given share of healthy drive-days raises an alert (the budget). At the main budget of 1.0%, 1.00% of validation drive-days alert for survival model, SMART + context; budgets of 0.1%, 0.3% are shown too. Test results: false alarms and precision are per drive-day; precision counts alerts whose outcome at 30 days is known, and the alerts that cannot be judged yet (panel end) are shown separately and, in the next column, counted as false. Failing drives alerted = drives failing in the test period that get at least one alert in their last 30 days.

| budget | model | false alarms, test (share of healthy drive-days) | precision (per alerted drive-day) | alerts with unknown outcome | precision, unknown as false | failing drives alerted (drives) | alerted >= 7 days before failure (drives) |
|---|---|---|---|---|---|---|---|
| 0.1% | survival model, SMART + context | 0.22% [0.17%, 0.26%] | 14.62% [12.42%, 17.43%] | 8.6% | 13.37% [11.31%, 16.03%] | 1044/1784, 59% [57%, 61%] | 791/1784 |
| 0.1% | survival model, context only (no SMART) | 0.03% [0.02%, 0.05%] | 0.69% [0.00%, 1.78%] | 0.0% | 0.69% [0.00%, 1.78%] | 3/1784, 0% [0%, 0%] | 3/1784 |
| 0.1% | 30-day yes/no classifier (SMART + context) | 0.32% [0.26%, 0.38%] | 11.63% [10.05%, 13.84%] | 8.8% | 10.61% [9.18%, 12.72%] | 1122/1784, 63% [61%, 65%] | 852/1784 |
| 0.1% | rule: critical SMART counters (5, 187, 197, 198) | 0.48% [0.35%, 0.58%] | 5.89% [4.83%, 7.84%] | 6.6% | 5.50% [4.53%, 7.30%] | 664/1784, 37% [35%, 39%] | 500/1784 |
| 0.1% | survival model, SMART + context, recalibrated on the last year | 0.21% [0.17%, 0.26%] | 14.63% [12.42%, 17.44%] | 8.6% | 13.37% [11.31%, 16.03%] | 1044/1784, 59% [57%, 61%] | 790/1784 |
| 0.3% | survival model, SMART + context | 0.70% [0.60%, 0.80%] | 7.59% [6.64%, 8.93%] | 7.4% | 7.03% [6.17%, 8.34%] | 1279/1784, 72% [69%, 74%] | 1051/1784 |
| 0.3% | survival model, context only (no SMART) | 0.36% [0.30%, 0.44%] | 0.29% [0.13%, 0.46%] | 2.2% | 0.28% [0.13%, 0.45%] | 17/1784, 1% [1%, 1%] | 15/1784 |
| 0.3% | 30-day yes/no classifier (SMART + context) | 0.81% [0.68%, 0.93%] | 6.93% [6.04%, 8.28%] | 7.5% | 6.41% [5.58%, 7.64%] | 1299/1784, 73% [71%, 75%] | 1078/1784 |
| 0.3% | rule: critical SMART counters (5, 187, 197, 198) | 0.79% [0.62%, 0.92%] | 4.84% [4.08%, 6.16%] | 6.9% | 4.51% [3.82%, 5.75%] | 839/1784, 47% [45%, 49%] | 664/1784 |
| 0.3% | survival model, SMART + context, recalibrated on the last year | 0.70% [0.60%, 0.80%] | 7.60% [6.64%, 8.93%] | 7.4% | 7.04% [6.17%, 8.34%] | 1279/1784, 72% [69%, 74%] | 1051/1784 |
| 1.0% | survival model, SMART + context | 1.57% [1.38%, 1.76%] | 4.37% [3.95%, 5.03%] | 6.3% | 4.09% [3.69%, 4.73%] | 1375/1784, 77% [75%, 79%] | 1184/1784 |
| 1.0% | survival model, context only (no SMART) | 1.11% [0.96%, 1.31%] | 0.27% [0.19%, 0.36%] | 12.4% | 0.23% [0.17%, 0.31%] | 47/1784, 3% [2%, 3%] | 46/1784 |
| 1.0% | 30-day yes/no classifier (SMART + context) | 1.98% [1.75%, 2.19%] | 3.62% [3.30%, 4.13%] | 6.4% | 3.39% [3.09%, 3.87%] | 1412/1784, 79% [77%, 81%] | 1215/1784 |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 6.0% | 2.88% [2.51%, 3.43%] | 1051/1784, 59% [57%, 61%] | 874/1784 |
| 1.0% | survival model, SMART + context, recalibrated on the last year | 1.57% [1.38%, 1.76%] | 4.37% [3.95%, 5.03%] | 6.3% | 4.09% [3.69%, 4.73%] | 1375/1784, 77% [75%, 79%] | 1184/1784 |

At the main budget the test false-alarm rate is above the budget, with an interval that excludes it, for survival model, SMART + context, 30-day yes/no classifier (SMART + context), rule: critical SMART counters (5, 187, 197, 198), survival model, SMART + context, recalibrated on the last year: healthy test drives score higher than the validation drives the threshold was set on. This is the same shift over time that Calibration over time shows (drift).

[Archived figure: detection](https://github.com/lazy-machine/hard-drive-analysis-v3/blob/2dc47742252d827c7ce3c5927efa19dc95424bcc/results/full-2026-11-09/report/detection.png)

## Calibration

Mean predicted failure probability vs the Kaplan-Meier observed share, by decile of predicted risk. Points on the diagonal mean that a predicted 5% really fails 5% of the time.

[Archived figure: calibration](https://github.com/lazy-machine/hard-drive-analysis-v3/blob/2dc47742252d827c7ce3c5927efa19dc95424bcc/results/full-2026-11-09/report/calibration.png)

**Calibration over time** (mean predicted vs observed risk of failing within 30 days; ratio = predicted / observed with a 95% drive bootstrap). Validation drives are from the training era, test from 2024 on. A gap that appears only in the test years is drift. "Outside band" = the test year's ratio is outside the range of the validation-year ratios. Reference = survival model, SMART + context; recalibrated = survival model, SMART + context, recalibrated on the last year.

| split | year | snapshots | observed | predicted (reference) | ratio (reference) | outside band (reference) | predicted (recalibrated) | ratio (recalibrated) | outside band (recalibrated) |
|---|---|---|---|---|---|---|---|---|---|
| val | 2016 | 70518 | 0.162% | 0.163% | 1.01 [0.85, 1.18] | - | 0.186% | 1.15 [0.97, 1.35] | - |
| val | 2017 | 85198 | 0.154% | 0.147% | 0.95 [0.78, 1.13] | - | 0.167% | 1.08 [0.88, 1.28] | - |
| val | 2018 | 102268 | 0.134% | 0.114% | 0.85 [0.71, 1.01] | - | 0.130% | 0.97 [0.82, 1.15] | - |
| val | 2019 | 116101 | 0.165% | 0.147% | 0.89 [0.71, 1.12] | - | 0.167% | 1.01 [0.81, 1.27] | - |
| val | 2020 | 137012 | 0.084% | 0.121% | 1.44 [1.18, 1.81] | - | 0.138% | 1.64 [1.35, 2.06] | - |
| val | 2021 | 169154 | 0.088% | 0.104% | 1.17 [1.00, 1.37] | - | 0.118% | 1.34 [1.15, 1.56] | - |
| val | 2022 | 191823 | 0.109% | 0.134% | 1.23 [1.08, 1.40] | - | 0.152% | 1.40 [1.23, 1.59] | - |
| val | 2023 | 205355 | 0.166% | 0.152% | 0.92 [0.83, 1.02] | - | 0.172% | 1.04 [0.93, 1.15] | - |
| test | 2024 | 422201 | 0.133% | 0.162% | 1.21 [1.11, 1.33] | no | 0.183% | 1.37 [1.26, 1.50] | no |
| test | 2025 | 403120 | 0.103% | 0.223% | 2.15 [1.87, 2.49] | yes | 0.250% | 2.42 [2.11, 2.80] | yes |

- survival model, SMART + context: predicted/observed ratio over validation years spans 0.85 to 1.44. The last validation year (2023, ratio 0.92) is inside the band of the earlier validation years. Test years outside the band: 2025.
- survival model, SMART + context, recalibrated on the last year: predicted/observed ratio over validation years spans 0.97 to 1.64. The last validation year (2023, ratio 1.04) is inside the band of the earlier validation years. Test years outside the band: 2025.

## Retirement

Drives that never fail and have snapshots in a year, split into those that stop reporting before the end of the next year (left) and those still reporting (stayed). The survival estimates assume that leaving is unrelated to health; then both groups would carry about the same predicted risk. A ratio above 1 means the drives that leave already looked riskier beforehand: censoring is probably informative (drives are retired before they can fail), and the observed failure risk is underestimated. The alert threshold is the main-budget threshold of survival model, SMART + context.

| split | year | drives left | drives stayed | mean predicted 30-day risk, left | mean predicted 30-day risk, stayed | ratio left/stayed | above alert threshold, left | above alert threshold, stayed |
|---|---|---|---|---|---|---|---|---|
| val | 2016 | 170 | 538 | 0.232% | 0.041% | 5.61 | 2.71% | 0.24% |
| val | 2017 | 280 | 672 | 0.202% | 0.041% | 4.94 | 2.38% | 0.20% |
| val | 2018 | 236 | 869 | 0.149% | 0.064% | 2.32 | 1.35% | 0.12% |
| val | 2019 | 233 | 964 | 0.124% | 0.105% | 1.19 | 0.30% | 0.51% |
| val | 2020 | 357 | 1270 | 0.139% | 0.062% | 2.25 | 1.03% | 0.23% |
| val | 2021 | 202 | 1828 | 0.124% | 0.057% | 2.17 | 1.08% | 0.16% |
| val | 2022 | 101 | 2040 | 0.167% | 0.068% | 2.46 | 3.17% | 0.32% |
| val | 2023 | 282 | 2383 | 0.178% | 0.079% | 2.26 | 2.28% | 0.55% |
| test | 2024 | 509 | 5809 | 0.206% | 0.102% | 2.03 | 1.78% | 0.90% |

The ratio is above 1 in 9 of 9 split-years with drives in both groups (no intervals: read it as a direction, not a test).

## Which SMART attributes matter

Single-attribute ROC-AUC on train snapshots (fails within 30 days), computed only on the drive-days where the attribute is reported; "filled" is that share. 0.5 = no signal. Below 0.5 means lower values go with failure (normalized values fall as a drive degrades).

| feature | ROC-AUC | filled |
|---|---|---|
| smart_187_raw | 0.699 | 64% |
| smart_187_normalized | 0.301 | 64% |
| smart_5_raw | 0.662 | 100% |
| smart_197_raw | 0.638 | 99% |
| smart_187_raw_d30 | 0.635 | 64% |
| smart_5_raw_d30 | 0.619 | 100% |
| smart_198_raw | 0.614 | 100% |
| smart_4_raw | 0.611 | 100% |
| smart_193_raw | 0.608 | 99% |
| smart_12_raw | 0.607 | 100% |
| smart_183_raw | 0.596 | 21% |
| smart_3_normalized | 0.406 | 100% |
| smart_187_raw_d7 | 0.592 | 64% |
| smart_5_raw_d7 | 0.589 | 100% |
| smart_196_raw | 0.589 | 36% |

[Archived figure: importance](https://github.com/lazy-machine/hard-drive-analysis-v3/blob/2dc47742252d827c7ce3c5927efa19dc95424bcc/results/full-2026-11-09/report/importance.png)

Also see `build/explore/km_by_counters.png` and `build/explore/models.csv`.


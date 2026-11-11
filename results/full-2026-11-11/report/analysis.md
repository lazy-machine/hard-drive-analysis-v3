# Can SMART data predict when a hard drive will fail?

The run itself (scale, cohort, test set, gate) and the headline numbers are in [results.md](results.md). This file explains them and holds the detailed tables.

## Answer

- **Do SMART metrics carry failure information?** Yes. Adding SMART to what is known without it (drive model, capacity, time in service) improves ROC-AUC at 5 of 5 horizons with a 95% interval that excludes zero:
  - 7 days: +0.302 [0.284, 0.316]
  - 30 days: +0.273 [0.260, 0.291]
  - 90 days: +0.234 [0.219, 0.253]
  - 180 days: +0.207 [0.194, 0.221]
  - 365 days: +0.203 [0.188, 0.219]
- **How much of that is the replacement policy?** Backblaze replaces drives when counters 5, 187, 188, 197 or 198 rise, so those counters partly define the failure label. The full model's ROC-AUC exceeds the model without them by +0.106 [0.098, 0.114] at 30 days (an interval above zero at 5 of 5 horizons). Part of the SMART gain above may be the operator's policy rather than physics; this comparison cannot say how much, because the dropped counters also carry physical signal.
- **How far ahead?** Ranking is strongest close to failure (ROC-AUC 0.905 for 7 days) and weaker for the long term (0.787 for 365 days; long horizons are measured on earlier test snapshots, see Discrimination by horizon).
- **But failures are rare.** Even within 7 days only 0.027% of drive-days fail. The model's PR-AUC there is 0.0650 (a random ranking would score about the base rate), so at any useful recall many alerts are false (see Early warning).
- **Is it more than the last days?** Counting as positives only snapshots >= 7 days before failure, the 30-day PR-AUC is 0.0784 [0.0654, 0.0964] against 0.1235 overall (base rate 0.093% vs 0.121%); ROC-AUC 0.868 [0.855, 0.877]. Much of the precision comes from the last days before failure.
- **Silent failures** (no critical counter above zero in any test snapshot): 368 of the 1784 failing test drives. On them the 30-day ROC-AUC of survival model, SMART + context is 0.638 [0.608, 0.666] against 0.877 [0.865, 0.886] overall: still above chance.
- **When will it probably fail?** When the model names a day within the next year, it is too pessimistic (drives fail later than predicted): 6.0% of the weighted snapshots had failed by their predicted 10% day, 33.7% by the predicted median and 79.8% by the predicted 90% day (targets 10/50/90%; IPCW, assuming censoring is unrelated to the failure time and to the predicted day). For drives that do fail within a year it names a median within a year only 15.0% of the time: the model rarely names a failure day months in advance. For healthy drives it says "more than a year" 99.9% of the time.
- **One survival model or a dedicated 30-day classifier?** At 30 days the survival model's ROC-AUC minus the classifier's is -0.001 [-0.004, 0.002] (paired bootstrap), PR-AUC +0.0053 [-0.0049, 0.0147]; the survival model is not better in 78% of rounds. Neither ranks clearly better, and the survival model also covers the other horizons.
- **Against the classic rule** (log-sum of the reallocated, reported-uncorrectable, pending and offline-uncorrectable sector counters 5, 187, 197, 198), the model gains +0.052 ROC-AUC [0.045, 0.060] at 7 days.

## Discrimination by horizon

ROC-AUC and PR-AUC per drive-day snapshot, on test snapshots whose status at the horizon is known, weighted to real prevalence. Brackets: 95% drive-level bootstrap (200 rounds). Base rate = real share of drive-days that fail within the horizon. All 1784 failing test drives are positive at every horizon (each has snapshots close to its failure day), so the last column counts positive snapshots instead.

| horizon | model | ROC-AUC | PR-AUC | Brier | base rate | positive snapshots |
|---|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.905 [0.895, 0.914] | 0.0650 [0.0534, 0.0816] | 0.00027 | 0.027% | 11632 |
| 7 d | survival model, context only (no SMART) | 0.603 [0.590, 0.617] | 0.0004 [0.0004, 0.0005] | 0.00027 | 0.027% | 11632 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0295 [0.0225, 0.0400] | n/a | 0.027% | 11632 |
| 30 d | survival model, SMART + context | 0.877 [0.865, 0.886] | 0.1235 [0.1053, 0.1466] | 0.00116 | 0.121% | 50334 |
| 30 d | survival model, context only (no SMART) | 0.603 [0.589, 0.616] | 0.0019 [0.0017, 0.0021] | 0.00121 | 0.121% | 50334 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.878 [0.868, 0.885] | 0.1182 [0.1006, 0.1373] | 0.00122 | 0.121% | 50334 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | n/a | 0.121% | 50334 |
| 90 d | survival model, SMART + context | 0.843 [0.832, 0.855] | 0.1821 [0.1582, 0.2103] | 0.00352 | 0.388% | 145601 |
| 90 d | survival model, context only (no SMART) | 0.609 [0.595, 0.623] | 0.0059 [0.0054, 0.0065] | 0.00387 | 0.388% | 145601 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.786 [0.776, 0.798] | 0.0893 [0.0733, 0.1164] | n/a | 0.388% | 145601 |
| 180 d | survival model, SMART + context | 0.813 [0.801, 0.825] | 0.2194 [0.1957, 0.2474] | 0.00757 | 0.865% | 163747 |
| 180 d | survival model, context only (no SMART) | 0.606 [0.594, 0.619] | 0.0131 [0.0122, 0.0142] | 0.00859 | 0.865% | 163747 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.755 [0.744, 0.764] | 0.1295 [0.1095, 0.1524] | n/a | 0.865% | 163747 |
| 365 d | survival model, SMART + context | 0.787 [0.777, 0.801] | 0.3117 [0.2888, 0.3389] | 0.01827 | 2.272% | 189708 |
| 365 d | survival model, context only (no SMART) | 0.585 [0.570, 0.602] | 0.0339 [0.0307, 0.0385] | 0.02222 | 2.272% | 189708 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.722 [0.711, 0.732] | 0.2145 [0.1873, 0.2420] | n/a | 2.272% | 189708 |

A horizon of H days needs H days of follow-up to know that a drive survived it, so the longer the horizon, the earlier the test snapshots it can use. The 365-day row uses only snapshots from roughly the first test year (2024); longer horizons are measured on an earlier, different calendar cohort than the short ones, so the rows are not a like-for-like trend. Test snapshots with a known status (825321 in total): 7 d: 819135 snapshots, known-healthy ones dated up to 2025-12-25; 30 d: 795715 snapshots, known-healthy ones dated up to 2025-12-02; 90 d: 735702 snapshots, known-healthy ones dated up to 2025-10-03; 180 d: 650242 snapshots, known-healthy ones dated up to 2025-07-05; 365 d: 485740 snapshots, known-healthy ones dated up to 2025-01-01.

**Robustness.** The same ranking with inverse-probability-of-censoring weights (IPCW: snapshots whose status is unknown are represented by weighting up comparable known ones, instead of being dropped), and a drive-level ROC-AUC on one random snapshot per drive, weighted per drive (so drives with many snapshots do not dominate). Brier skill = 1 - Brier / Brier of always predicting the base rate; above 0 beats that constant.

| horizon | model | ROC-AUC, IPCW (per drive-day) | PR-AUC, IPCW (per drive-day) | ROC-AUC (per drive) | Brier skill |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.905 [0.895, 0.914] | 0.0646 [0.0532, 0.0811] | 0.900 [0.842, 0.938] | -0.003 |
| 7 d | survival model, context only (no SMART) | 0.603 [0.590, 0.617] | 0.0004 [0.0004, 0.0005] | 0.618 [0.565, 0.667] | -0.000 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0294 [0.0224, 0.0399] | 0.827 [0.763, 0.866] | n/a |
| 30 d | survival model, SMART + context | 0.876 [0.865, 0.885] | 0.1206 [0.1027, 0.1434] | 0.862 [0.838, 0.886] | 0.042 |
| 30 d | survival model, context only (no SMART) | 0.603 [0.589, 0.616] | 0.0018 [0.0017, 0.0020] | 0.612 [0.585, 0.638] | -0.001 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.878 [0.867, 0.885] | 0.1155 [0.0981, 0.1343] | 0.865 [0.843, 0.888] | -0.015 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0509 [0.0399, 0.0705] | 0.811 [0.785, 0.836] | n/a |
| 90 d | survival model, SMART + context | 0.842 [0.831, 0.854] | 0.1700 [0.1474, 0.1979] | 0.831 [0.817, 0.848] | 0.090 |
| 90 d | survival model, context only (no SMART) | 0.609 [0.595, 0.623] | 0.0054 [0.0050, 0.0060] | 0.619 [0.601, 0.637] | -0.002 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.774, 0.797] | 0.0825 [0.0675, 0.1088] | 0.782 [0.768, 0.799] | n/a |
| 180 d | survival model, SMART + context | 0.809 [0.797, 0.822] | 0.1892 [0.1674, 0.2162] | 0.827 [0.815, 0.843] | 0.117 |
| 180 d | survival model, context only (no SMART) | 0.606 [0.594, 0.619] | 0.0110 [0.0103, 0.0120] | 0.630 [0.614, 0.644] | -0.002 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.751 [0.740, 0.760] | 0.1094 [0.0915, 0.1308] | 0.778 [0.764, 0.791] | n/a |
| 365 d | survival model, SMART + context | 0.775 [0.764, 0.789] | 0.2292 [0.2066, 0.2576] | 0.829 [0.817, 0.845] | 0.177 |
| 365 d | survival model, context only (no SMART) | 0.586 [0.571, 0.604] | 0.0212 [0.0192, 0.0242] | 0.611 [0.597, 0.628] | -0.000 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.710 [0.699, 0.720] | 0.1497 [0.1253, 0.1765] | 0.768 [0.755, 0.781] | n/a |

![AUC by horizon](auc_by_horizon.png)

## Ablations and sensitivity

Each variant against the reference (survival model, SMART + context). Gain = reference minus variant, paired on the same bootstrap rounds; "not better" = share of rounds where the reference's ROC-AUC is not higher.

- **survival model, SMART without counters 5/187/188/197/198**: drops counters 5, 187, 188, 197 and 198 (raw, normalized and trends), the ones behind Backblaze's own replacement decisions. A drive replaced because these counters rose is recorded as failed, so part of the full model's SMART signal may be the replacement policy itself. Dropping the counters also drops their physical signal, and other features can still track them, so this is a sensitivity check, not a clean split of policy from physics.
- **survival model, context + usage counters**: context plus the usage counters only (4, 9, 12, 193, 240-242: power-on hours, start/stop and power cycles, load cycles, head flying hours, LBAs written and read). Tests whether SMART helps only because it measures age and wear.
- **survival model, SMART + context, weight power 0.75**: the reference features with training weights to the power 0.75 instead of 0.5. Tests how much the ranking depends on the weight exponent.
- **survival model, SMART + context, weight power 1.0**: the same with the full inverse-probability weights (power 1.0).
- **survival model, SMART + context, recalibrated on the last year**: the reference trees with probabilities recalibrated on the last validation year before the training cutoff. Tests whether a recent recalibration fixes drift (see Calibration over time); the trees are the same, so ranking changes only through the per-bin recalibration.

| horizon | model | ROC-AUC | reference gain, ROC-AUC | reference gain, PR-AUC | not better |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context (reference) | 0.905 [0.895, 0.914] |  |  |  |
| 7 d | survival model, SMART without counters 5/187/188/197/198 | 0.799 [0.787, 0.813] | +0.106 [0.096, 0.115] | +0.0424 [0.0329, 0.0562] | 0% |
| 7 d | survival model, context + usage counters | 0.655 [0.640, 0.668] | +0.250 [0.235, 0.262] | +0.0642 [0.0527, 0.0808] | 0% |
| 7 d | survival model, SMART + context, weight power 0.75 | 0.907 [0.897, 0.915] | -0.002 [-0.004, 0.000] | +0.0009 [-0.0029, 0.0068] | 96% |
| 7 d | survival model, SMART + context, weight power 1.0 | 0.904 [0.894, 0.913] | +0.001 [-0.002, 0.005] | +0.0100 [0.0038, 0.0178] | 18% |
| 7 d | survival model, SMART + context, recalibrated on the last year | 0.905 [0.895, 0.914] | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] | 100% |
| 30 d | survival model, SMART + context (reference) | 0.877 [0.865, 0.886] |  |  |  |
| 30 d | survival model, SMART without counters 5/187/188/197/198 | 0.770 [0.758, 0.784] | +0.106 [0.098, 0.114] | +0.0821 [0.0624, 0.1007] | 0% |
| 30 d | survival model, context + usage counters | 0.654 [0.642, 0.666] | +0.222 [0.211, 0.236] | +0.1208 [0.1025, 0.1438] | 0% |
| 30 d | survival model, SMART + context, weight power 0.75 | 0.880 [0.868, 0.888] | -0.003 [-0.006, -0.000] | +0.0063 [-0.0008, 0.0142] | 100% |
| 30 d | survival model, SMART + context, weight power 1.0 | 0.877 [0.866, 0.886] | -0.000 [-0.003, 0.003] | +0.0190 [0.0074, 0.0297] | 56% |
| 30 d | survival model, SMART + context, recalibrated on the last year | 0.877 [0.865, 0.886] | -0.000 [-0.000, -0.000] | +0.0000 [0.0000, 0.0001] | 98% |
| 90 d | survival model, SMART + context (reference) | 0.843 [0.832, 0.855] |  |  |  |
| 90 d | survival model, SMART without counters 5/187/188/197/198 | 0.745 [0.730, 0.758] | +0.098 [0.090, 0.110] | +0.1236 [0.1020, 0.1505] | 0% |
| 90 d | survival model, context + usage counters | 0.656 [0.644, 0.669] | +0.187 [0.175, 0.203] | +0.1748 [0.1512, 0.2029] | 0% |
| 90 d | survival model, SMART + context, weight power 0.75 | 0.846 [0.835, 0.858] | -0.003 [-0.006, 0.000] | +0.0108 [0.0035, 0.0183] | 94% |
| 90 d | survival model, SMART + context, weight power 1.0 | 0.845 [0.833, 0.857] | -0.002 [-0.005, 0.002] | +0.0187 [0.0069, 0.0282] | 82% |
| 90 d | survival model, SMART + context, recalibrated on the last year | 0.843 [0.832, 0.855] | +0.000 [0.000, 0.000] | +0.0003 [0.0001, 0.0004] | 0% |
| 180 d | survival model, SMART + context (reference) | 0.813 [0.801, 0.825] |  |  |  |
| 180 d | survival model, SMART without counters 5/187/188/197/198 | 0.720 [0.707, 0.733] | +0.093 [0.084, 0.102] | +0.1401 [0.1137, 0.1671] | 0% |
| 180 d | survival model, context + usage counters | 0.658 [0.644, 0.671] | +0.155 [0.143, 0.167] | +0.2030 [0.1799, 0.2308] | 0% |
| 180 d | survival model, SMART + context, weight power 0.75 | 0.813 [0.802, 0.825] | -0.000 [-0.004, 0.003] | +0.0193 [0.0071, 0.0321] | 52% |
| 180 d | survival model, SMART + context, weight power 1.0 | 0.812 [0.800, 0.824] | +0.001 [-0.003, 0.005] | +0.0303 [0.0179, 0.0421] | 32% |
| 180 d | survival model, SMART + context, recalibrated on the last year | 0.813 [0.801, 0.825] | -0.000 [-0.000, -0.000] | +0.0001 [0.0001, 0.0002] | 100% |
| 365 d | survival model, SMART + context (reference) | 0.787 [0.777, 0.801] |  |  |  |
| 365 d | survival model, SMART without counters 5/187/188/197/198 | 0.712 [0.699, 0.728] | +0.075 [0.067, 0.084] | +0.1702 [0.1407, 0.1928] | 0% |
| 365 d | survival model, context + usage counters | 0.664 [0.652, 0.679] | +0.123 [0.110, 0.135] | +0.2652 [0.2424, 0.2916] | 0% |
| 365 d | survival model, SMART + context, weight power 0.75 | 0.787 [0.776, 0.800] | +0.000 [-0.003, 0.004] | +0.0152 [0.0006, 0.0308] | 47% |
| 365 d | survival model, SMART + context, weight power 1.0 | 0.787 [0.775, 0.801] | -0.000 [-0.004, 0.004] | +0.0304 [0.0154, 0.0453] | 55% |
| 365 d | survival model, SMART + context, recalibrated on the last year | 0.787 [0.777, 0.801] | -0.000 [-0.000, -0.000] | -0.0004 [-0.0008, -0.0001] | 100% |

## Where the signal comes from

The ranking metrics on parts of the test set, per drive-day snapshot. Positive-side slices (lead time, silent or not) keep every known-healthy snapshot and restrict the failing ones, so their base rate is lower; population slices (vendor, capacity, entry date) restrict both. "Silent" failures are drives that fail with none of the critical counters (5, 187, 197, 198) above zero in any test snapshot. At 30 days:

| slice | model | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| all test snapshots | survival model, SMART + context | 0.877 [0.865, 0.886] | 0.1235 [0.1053, 0.1466] | 0.121% | 1784 |
| all test snapshots | survival model, context only (no SMART) | 0.603 [0.589, 0.616] | 0.0019 [0.0017, 0.0021] | 0.121% | 1784 |
| all test snapshots | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | 0.121% | 1784 |
| positives >= 7 days before failure | survival model, SMART + context | 0.868 [0.855, 0.877] | 0.0784 [0.0654, 0.0964] | 0.093% | 1755 |
| positives >= 7 days before failure | survival model, context only (no SMART) | 0.604 [0.589, 0.616] | 0.0014 [0.0013, 0.0016] | 0.093% | 1755 |
| positives >= 7 days before failure | rule: critical SMART counters (5, 187, 197, 198) | 0.814 [0.804, 0.825] | 0.0333 [0.0259, 0.0485] | 0.093% | 1755 |
| silent failures (no critical counter above zero) | survival model, SMART + context | 0.638 [0.608, 0.666] | 0.0007 [0.0004, 0.0011] | 0.025% | 368 |
| silent failures (no critical counter above zero) | survival model, context only (no SMART) | 0.562 [0.530, 0.593] | 0.0003 [0.0003, 0.0004] | 0.025% | 368 |
| silent failures (no critical counter above zero) | rule: critical SMART counters (5, 187, 197, 198) | 0.473 [0.470, 0.475] | 0.0002 [0.0002, 0.0003] | 0.025% | 368 |
| failures with a critical counter above zero | survival model, SMART + context | 0.939 [0.932, 0.945] | 0.1496 [0.1253, 0.1783] | 0.096% | 1416 |
| failures with a critical counter above zero | survival model, context only (no SMART) | 0.614 [0.597, 0.627] | 0.0016 [0.0014, 0.0018] | 0.096% | 1416 |
| failures with a critical counter above zero | rule: critical SMART counters (5, 187, 197, 198) | 0.915 [0.907, 0.922] | 0.0653 [0.0519, 0.0892] | 0.096% | 1416 |
| vendor HGST | survival model, SMART + context | 0.931 [0.916, 0.947] | 0.0883 [0.0663, 0.1323] | 0.235% | 380 |
| vendor HGST | survival model, context only (no SMART) | 0.599 [0.573, 0.631] | 0.0045 [0.0029, 0.0075] | 0.235% | 380 |
| vendor HGST | rule: critical SMART counters (5, 187, 197, 198) | 0.888 [0.870, 0.908] | 0.0436 [0.0317, 0.0727] | 0.235% | 380 |
| vendor Seagate | survival model, SMART + context | 0.897 [0.882, 0.910] | 0.1698 [0.1390, 0.2091] | 0.139% | 764 |
| vendor Seagate | survival model, context only (no SMART) | 0.618 [0.598, 0.637] | 0.0023 [0.0020, 0.0028] | 0.139% | 764 |
| vendor Seagate | rule: critical SMART counters (5, 187, 197, 198) | 0.852 [0.837, 0.868] | 0.0881 [0.0659, 0.1332] | 0.139% | 764 |
| vendor Toshiba | survival model, SMART + context | 0.779 [0.752, 0.804] | 0.1268 [0.1043, 0.1536] | 0.104% | 485 |
| vendor Toshiba | survival model, context only (no SMART) | 0.515 [0.488, 0.536] | 0.0013 [0.0010, 0.0028] | 0.104% | 485 |
| vendor Toshiba | rule: critical SMART counters (5, 187, 197, 198) | 0.740 [0.716, 0.760] | 0.0674 [0.0516, 0.0973] | 0.104% | 485 |
| vendor WDC | survival model, SMART + context | 0.826 [0.784, 0.874] | 0.0773 [0.0448, 0.1366] | 0.054% | 155 |
| vendor WDC | survival model, context only (no SMART) | 0.527 [0.480, 0.572] | 0.0007 [0.0005, 0.0018] | 0.054% | 155 |
| vendor WDC | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.751, 0.823] | 0.0427 [0.0280, 0.0775] | 0.054% | 155 |
| capacity >= 16 TB | survival model, SMART + context | 0.814 [0.792, 0.835] | 0.0769 [0.0547, 0.1076] | 0.075% | 530 |
| capacity >= 16 TB | survival model, context only (no SMART) | 0.585 [0.563, 0.613] | 0.0011 [0.0009, 0.0013] | 0.075% | 530 |
| capacity >= 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.754 [0.733, 0.773] | 0.0396 [0.0293, 0.0645] | 0.075% | 530 |
| capacity < 16 TB | survival model, SMART + context | 0.902 [0.890, 0.912] | 0.1456 [0.1219, 0.1778] | 0.165% | 1254 |
| capacity < 16 TB | survival model, context only (no SMART) | 0.528 [0.510, 0.543] | 0.0022 [0.0019, 0.0025] | 0.165% | 1254 |
| capacity < 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.850 [0.838, 0.863] | 0.0591 [0.0453, 0.0873] | 0.165% | 1254 |
| in service before the panel starts | survival model, SMART + context | 0.910 [0.315, 0.985] | 0.1609 [0.0001, 0.8890] | 0.100% | 5 |
| in service before the panel starts | survival model, context only (no SMART) | 0.637 [0.293, 0.980] | 0.0142 [0.0001, 0.1640] | 0.100% | 5 |
| in service before the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.482 [0.447, 0.611] | 0.0010 [0.0001, 0.0024] | 0.100% | 5 |
| first seen after the panel starts | survival model, SMART + context | 0.877 [0.865, 0.886] | 0.1237 [0.1055, 0.1476] | 0.121% | 1779 |
| first seen after the panel starts | survival model, context only (no SMART) | 0.603 [0.589, 0.616] | 0.0019 [0.0017, 0.0021] | 0.121% | 1779 |
| first seen after the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.824 [0.814, 0.833] | 0.0522 [0.0410, 0.0721] | 0.121% | 1779 |
| vendor Toshiba without MG08ACA16TEY | survival model, SMART + context | 0.816 [0.791, 0.841] | 0.1428 [0.1173, 0.1739] | 0.091% | 411 |
| vendor Toshiba without MG08ACA16TEY | survival model, context only (no SMART) | 0.497 [0.463, 0.518] | 0.0011 [0.0009, 0.0029] | 0.091% | 411 |
| vendor Toshiba without MG08ACA16TEY | rule: critical SMART counters (5, 187, 197, 198) | 0.756 [0.730, 0.777] | 0.0787 [0.0564, 0.1160] | 0.091% | 411 |
| silent failures vs negatives with no critical counter | survival model, SMART + context | 0.669 [0.638, 0.697] | 0.0279 [0.0134, 0.0429] | 0.026% | 368 |
| silent failures vs negatives with no critical counter | survival model, context only (no SMART) | 0.571 [0.539, 0.602] | 0.0004 [0.0003, 0.0004] | 0.026% | 368 |
| silent failures vs negatives with no critical counter | rule: critical SMART counters (5, 187, 197, 198) | 0.500 [0.500, 0.500] | 0.0003 [0.0002, 0.0003] | 0.026% | 368 |

The same two slices for survival model, SMART + context across horizons:

| slice | horizon | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| silent failures (no critical counter above zero) | 7 d | 0.655 [0.624, 0.684] | 0.0002 [0.0001, 0.0004] | 0.006% | 368 |
| silent failures (no critical counter above zero) | 30 d | 0.638 [0.608, 0.666] | 0.0007 [0.0004, 0.0011] | 0.025% | 368 |
| silent failures (no critical counter above zero) | 90 d | 0.617 [0.586, 0.645] | 0.0015 [0.0012, 0.0021] | 0.078% | 368 |
| silent failures (no critical counter above zero) | 180 d | 0.589 [0.558, 0.627] | 0.0029 [0.0024, 0.0040] | 0.172% | 368 |
| silent failures (no critical counter above zero) | 365 d | 0.581 [0.549, 0.618] | 0.0076 [0.0061, 0.0102] | 0.452% | 368 |
| silent failures vs negatives with no critical counter | 7 d | 0.686 [0.655, 0.716] | 0.0161 [0.0090, 0.0293] | 0.006% | 368 |
| silent failures vs negatives with no critical counter | 30 d | 0.669 [0.638, 0.697] | 0.0279 [0.0134, 0.0429] | 0.026% | 368 |
| silent failures vs negatives with no critical counter | 90 d | 0.647 [0.613, 0.675] | 0.0190 [0.0110, 0.0306] | 0.083% | 368 |
| silent failures vs negatives with no critical counter | 180 d | 0.616 [0.583, 0.655] | 0.0190 [0.0103, 0.0294] | 0.182% | 368 |
| silent failures vs negatives with no critical counter | 365 d | 0.605 [0.573, 0.642] | 0.0271 [0.0166, 0.0425] | 0.474% | 368 |
| positives >= 7 days before failure | 30 d | 0.868 [0.855, 0.877] | 0.0784 [0.0654, 0.0964] | 0.093% | 1755 |
| positives >= 7 days before failure | 90 d | 0.838 [0.827, 0.850] | 0.1532 [0.1314, 0.1792] | 0.357% | 1757 |
| positives >= 7 days before failure | 180 d | 0.809 [0.797, 0.822] | 0.1987 [0.1760, 0.2261] | 0.829% | 1758 |
| positives >= 7 days before failure | 365 d | 0.784 [0.774, 0.798] | 0.2973 [0.2738, 0.3249] | 2.215% | 1758 |

## Ranking over the whole future (concordance)

Concordance between each model's risk score and the actual time to failure; 0.5 = random. Harrell's C counts the comparable pairs (the earlier time is a failure) where the riskier snapshot fails first. Uno's C weights each pair by the inverse probability of staying uncensored, so it does not depend on how much follow-up the test period allows, and is truncated at 365 days. Computed on 299930 test snapshots of 3267 drives (drives sampled whole up to a row cap). Score: -rmst_days = minus the expected days survived within a year; p30 = predicted 30-day risk, so hazard models can be compared with the classifier on the same kind of score. Intervals only on each model's main score.

| model | score | Harrell's C | Uno's C |
|---|---|---|---|
| survival model, SMART + context | -rmst_days | 0.762 [0.739, 0.779] | 0.756 [0.733, 0.774] |
| survival model, SMART + context | p30 | 0.771 | 0.766 |
| survival model, context only (no SMART) | -rmst_days | 0.593 [0.567, 0.612] | 0.595 [0.569, 0.615] |
| survival model, context only (no SMART) | p30 | 0.601 | 0.602 |
| 30-day yes/no classifier (SMART + context) | p30 | 0.777 [0.756, 0.794] | 0.773 [0.753, 0.791] |
| rule: critical SMART counters (5, 187, 197, 198) | score | 0.717 [0.698, 0.730] | 0.709 [0.689, 0.723] |
| survival model, SMART without counters 5/187/188/197/198 | -rmst_days | 0.679 [0.657, 0.709] | 0.675 [0.653, 0.704] |
| survival model, SMART without counters 5/187/188/197/198 | p30 | 0.689 | 0.685 |
| survival model, context + usage counters | -rmst_days | 0.630 [0.609, 0.656] | 0.632 [0.610, 0.657] |
| survival model, context + usage counters | p30 | 0.633 | 0.634 |
| survival model, SMART + context, weight power 0.75 | -rmst_days | 0.764 [0.744, 0.780] | 0.757 [0.738, 0.773] |
| survival model, SMART + context, weight power 0.75 | p30 | 0.782 | 0.777 |
| survival model, SMART + context, weight power 1.0 | -rmst_days | 0.766 [0.744, 0.782] | 0.759 [0.738, 0.777] |
| survival model, SMART + context, weight power 1.0 | p30 | 0.783 | 0.778 |
| survival model, SMART + context, recalibrated on the last year | -rmst_days | 0.762 [0.739, 0.780] | 0.756 [0.733, 0.774] |
| survival model, SMART + context, recalibrated on the last year | p30 | 0.771 | 0.766 |

## When will it fail? Remaining-life estimates

From each snapshot the survival model gives a curve: the day by which the failure probability reaches 10%, 50% (the median remaining life) and 90%. Beyond 365 days the model has no bins, so the answer is "more than a year". For 0.5% of all test snapshots the predicted median of survival model, SMART + context is within a year; otherwise the answer is "more than a year".

**Are the predicted days right?** Among snapshots whose predicted day falls within a year, the weighted share of snapshots that actually failed by that day should be close to the target. A snapshot censored before its outcome is known is dropped, which favours snapshots with an early day. So the first share is IPCW: each known failure is weighted by 1 / P(still uncensored on its failure day) and each known survivor by 1 / P(still uncensored the day before its predicted day), from one Kaplan-Meier curve of the censoring time. That is unbiased only if censoring is unrelated to both the failure time and the predicted day; most censoring is the panel's end, which depends on the snapshot date, so read it as an adjusted estimate. The share over known outcomes only is in brackets. Neither corrects for retirement related to health, which the retirement check below questions.

| model | failed by predicted 10% day | failed by predicted median | failed by predicted 90% day |
|---|---|---|---|
| survival model, SMART + context | 6.0% [5.3%, 6.8%] [7.0%] (target 10%, 113802 snapshots) | 33.7% [28.2%, 41.3%] [38.3%] (target 50%, 45249 snapshots) | 79.8% [73.5%, 85.6%] [82.5%] (target 90%, 7981 snapshots) |
| survival model, context only (no SMART) | 3.7% [2.0%, 5.8%] [4.6%] (target 10%, 3112 snapshots) | n/a [n/a] [n/a] (target 50%, 0 snapshots) | n/a [n/a] [n/a] (target 90%, 0 snapshots) |
| survival model, SMART without counters 5/187/188/197/198 | 6.1% [5.2%, 7.3%] [7.5%] (target 10%, 52025 snapshots) | 24.3% [15.5%, 48.5%] [26.7%] (target 50%, 8644 snapshots) | 14.2% [5.1%, 64.6%] [22.0%] (target 90%, 1790 snapshots) |
| survival model, context + usage counters | 3.6% [2.6%, 4.7%] [4.5%] (target 10%, 13345 snapshots) | 100.0% [100.0%, 100.0%] [100.0%] (target 50%, 24 snapshots) | n/a [n/a] [n/a] (target 90%, 0 snapshots) |
| survival model, SMART + context, weight power 0.75 | 6.1% [5.4%, 7.1%] [7.2%] (target 10%, 112877 snapshots) | 29.2% [24.1%, 37.2%] [32.9%] (target 50%, 47278 snapshots) | 70.2% [62.3%, 80.3%] [75.9%] (target 90%, 10616 snapshots) |
| survival model, SMART + context, weight power 1.0 | 6.6% [5.8%, 7.7%] [7.6%] (target 10%, 106979 snapshots) | 24.3% [19.8%, 31.7%] [27.6%] (target 50%, 47603 snapshots) | 36.7% [26.5%, 54.8%] [45.5%] (target 90%, 17337 snapshots) |
| survival model, SMART + context, recalibrated on the last year | 5.0% [4.5%, 5.6%] [5.8%] (target 10%, 118969 snapshots) | 28.2% [23.8%, 34.4%] [32.3%] (target 50%, 53022 snapshots) | 70.6% [64.0%, 78.2%] [75.1%] (target 90%, 12689 snapshots) |

**How early is a failure visible?** Snapshots of drives that do fail within a year, by how far away the failure actually was. A median within a year means the model already expects the drive to die within a year. The absolute error is over the failing snapshots whose median is within a year (count in brackets):

| model | failing snapshots: median within a year | abs. error of median (days) | all test snapshots: median within a year | healthy snapshots: median beyond a year |
|---|---|---|---|---|
| survival model, SMART + context | 15.0% [14.0%, 16.3%] | 110 [106, 114] (43922 snapshots) | 0.5% | 99.9% |
| survival model, context only (no SMART) | 0.0% [0.0%, 0.0%] | n/a [n/a] (0 snapshots) | 0.0% | 100.0% |
| survival model, SMART without counters 5/187/188/197/198 | 2.8% [2.2%, 3.3%] | 100 [91, 112] (8316 snapshots) | 0.1% | 100.0% |
| survival model, context + usage counters | 0.0% [0.0%, 0.0%] | 112 [112, 112] (24 snapshots) | 0.0% | 100.0% |
| survival model, SMART + context, weight power 0.75 | 16.0% [14.9%, 17.2%] | 107 [102, 110] (45547 snapshots) | 0.5% | 99.8% |
| survival model, SMART + context, weight power 1.0 | 16.4% [15.1%, 17.9%] | 98 [94, 101] (45476 snapshots) | 0.6% | 99.7% |
| survival model, SMART + context, recalibrated on the last year | 18.1% [16.9%, 19.4%] | 102 [98, 105] (51101 snapshots) | 0.6% | 99.8% |

By actual time to failure (survival model, SMART + context). Shares are of the failing drives' snapshots in each bucket:

| actual days to failure | snapshots | median predicted within a year | median of predicted median (days) |
|---|---|---|---|
| 0-6 | 11632 | 47.5% | > 1 year |
| 7-13 | 11720 | 38.5% | > 1 year |
| 14-29 | 26982 | 32.5% | > 1 year |
| 30-59 | 48813 | 24.9% | > 1 year |
| 60-89 | 46454 | 19.1% | > 1 year |
| 90-179 | 18146 | 12.5% | > 1 year |
| 180-364 | 25961 | 6.9% | > 1 year |

![remaining life](remaining_life.png)

## Early warning

Each alert threshold is set on validation drives so that a given share of healthy drive-days raises an alert (the budget). At the main budget of 1.0%, 1.00% of validation drive-days alert for survival model, SMART + context; budgets of 0.1%, 0.3% are shown too. Test results: false alarms and precision are per drive-day; precision counts alerts whose outcome at 30 days is known, and the alerts that cannot be judged yet (panel end) are shown separately and, in the next column, counted as false. Failing drives alerted = drives failing in the test period that get at least one alert in their last 30 days.

| budget | model | false alarms, test (share of healthy drive-days) | precision (per alerted drive-day) | alerts with unknown outcome | precision, unknown as false | failing drives alerted (drives) | alerted >= 7 days before failure (drives) |
|---|---|---|---|---|---|---|---|
| 0.1% | survival model, SMART + context | 0.21% [0.16%, 0.25%] | 15.26% [12.78%, 18.37%] | 8.6% | 13.94% [11.75%, 16.81%] | 1020/1784, 57% [55%, 59%] | 763/1784 |
| 0.1% | survival model, context only (no SMART) | 0.11% [0.06%, 0.16%] | 0.35% [0.07%, 0.73%] | 2.0% | 0.34% [0.07%, 0.72%] | 6/1784, 0% [0%, 1%] | 6/1784 |
| 0.1% | 30-day yes/no classifier (SMART + context) | 0.32% [0.26%, 0.38%] | 11.73% [9.96%, 14.21%] | 9.0% | 10.67% [9.08%, 12.86%] | 1120/1784, 63% [61%, 65%] | 866/1784 |
| 0.1% | rule: critical SMART counters (5, 187, 197, 198) | 0.48% [0.35%, 0.58%] | 5.89% [4.83%, 7.84%] | 6.6% | 5.50% [4.53%, 7.30%] | 664/1784, 37% [35%, 39%] | 500/1784 |
| 0.1% | survival model, SMART + context, recalibrated on the last year | 0.21% [0.16%, 0.25%] | 15.23% [12.76%, 18.35%] | 8.6% | 13.92% [11.75%, 16.77%] | 1017/1784, 57% [55%, 59%] | 761/1784 |
| 0.3% | survival model, SMART + context | 0.57% [0.48%, 0.66%] | 8.69% [7.62%, 10.39%] | 7.6% | 8.03% [7.04%, 9.64%] | 1246/1784, 70% [68%, 72%] | 1015/1784 |
| 0.3% | survival model, context only (no SMART) | 0.38% [0.28%, 0.50%] | 0.58% [0.39%, 0.91%] | 4.2% | 0.56% [0.37%, 0.88%] | 36/1784, 2% [1%, 3%] | 35/1784 |
| 0.3% | 30-day yes/no classifier (SMART + context) | 0.72% [0.61%, 0.83%] | 7.45% [6.52%, 8.87%] | 7.8% | 6.87% [6.00%, 8.16%] | 1270/1784, 71% [69%, 73%] | 1051/1784 |
| 0.3% | rule: critical SMART counters (5, 187, 197, 198) | 0.79% [0.62%, 0.92%] | 4.84% [4.08%, 6.16%] | 6.9% | 4.51% [3.82%, 5.75%] | 839/1784, 47% [45%, 49%] | 664/1784 |
| 0.3% | survival model, SMART + context, recalibrated on the last year | 0.57% [0.48%, 0.67%] | 8.69% [7.62%, 10.39%] | 7.6% | 8.03% [7.05%, 9.64%] | 1247/1784, 70% [68%, 72%] | 1015/1784 |
| 1.0% | survival model, SMART + context | 1.87% [1.64%, 2.07%] | 3.82% [3.45%, 4.40%] | 6.5% | 3.57% [3.23%, 4.12%] | 1391/1784, 78% [76%, 80%] | 1203/1784 |
| 1.0% | survival model, context only (no SMART) | 2.55% [2.31%, 2.87%] | 0.33% [0.27%, 0.40%] | 10.0% | 0.30% [0.24%, 0.36%] | 141/1784, 8% [7%, 9%] | 135/1784 |
| 1.0% | 30-day yes/no classifier (SMART + context) | 2.22% [1.99%, 2.44%] | 3.30% [3.02%, 3.70%] | 6.5% | 3.08% [2.82%, 3.48%] | 1426/1784, 80% [78%, 82%] | 1231/1784 |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 6.0% | 2.88% [2.51%, 3.43%] | 1051/1784, 59% [57%, 61%] | 874/1784 |
| 1.0% | survival model, SMART + context, recalibrated on the last year | 1.86% [1.64%, 2.07%] | 3.82% [3.45%, 4.40%] | 6.5% | 3.57% [3.23%, 4.12%] | 1390/1784, 78% [76%, 80%] | 1203/1784 |

At the main budget the test false-alarm rate is above the budget, with an interval that excludes it, for survival model, SMART + context, survival model, context only (no SMART), 30-day yes/no classifier (SMART + context), rule: critical SMART counters (5, 187, 197, 198), survival model, SMART + context, recalibrated on the last year: healthy test drives score higher than the validation drives the threshold was set on. This is the same shift over time that Calibration over time shows (drift).

**Per drive.** Non-failing drives = test drives that do not fail in the test period. Alerted = at least one alert on any of their test snapshots, which are weekly, so a daily monitor would alert at least as many. The last column divides the alerted non-failing drives by the failing drives alerted in their last 30 days (both weighted to the fleet).

| budget | model | non-failing drives alerted | per failing drive alerted |
|---|---|---|---|
| 0.1% | survival model, SMART + context | 1.4% [1.2%, 1.7%] | 1.0 [0.8, 1.2] |
| 0.1% | survival model, context only (no SMART) | 0.3% [0.2%, 0.4%] | 35.0 [19.1, 112.0] |
| 0.1% | 30-day yes/no classifier (SMART + context) | 2.1% [1.8%, 2.4%] | 1.4 [1.1, 1.6] |
| 0.1% | rule: critical SMART counters (5, 187, 197, 198) | 0.8% [0.6%, 0.9%] | 0.8 [0.6, 1.0] |
| 0.1% | survival model, SMART + context, recalibrated on the last year | 1.4% [1.2%, 1.7%] | 1.0 [0.8, 1.2] |
| 0.3% | survival model, SMART + context | 3.8% [3.4%, 4.2%] | 2.2 [2.0, 2.5] |
| 0.3% | survival model, context only (no SMART) | 0.7% [0.5%, 0.8%] | 13.1 [8.8, 19.7] |
| 0.3% | 30-day yes/no classifier (SMART + context) | 4.1% [3.7%, 4.5%] | 2.3 [2.1, 2.6] |
| 0.3% | rule: critical SMART counters (5, 187, 197, 198) | 1.4% [1.1%, 1.6%] | 1.2 [0.9, 1.4] |
| 0.3% | survival model, SMART + context, recalibrated on the last year | 3.8% [3.4%, 4.2%] | 2.2 [1.9, 2.5] |
| 1.0% | survival model, SMART + context | 7.9% [7.3%, 8.5%] | 4.1 [3.8, 4.4] |
| 1.0% | survival model, context only (no SMART) | 10.4% [9.8%, 11.2%] | 53.2 [44.2, 63.1] |
| 1.0% | 30-day yes/no classifier (SMART + context) | 13.6% [12.9%, 14.5%] | 6.9 [6.5, 7.4] |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 2.4% [2.1%, 2.8%] | 1.7 [1.4, 1.9] |
| 1.0% | survival model, SMART + context, recalibrated on the last year | 7.9% [7.3%, 8.5%] | 4.1 [3.8, 4.4] |

**Per drive, one schedule.** Every drive judged only on its weekly snapshots (every 7 days): a failing drive is caught if one in its last 30 days alerts (1766 of 1784 failing drives have one), a non-failing drive is a false alarm if any of its test-period ones alerts. Thresholds from validation, as above.

| budget | model | failing drives caught | non-failing drives alerted |
|---|---|---|---|
| 0.1% | survival model, SMART + context | 46.5% [44.4%, 48.9%] | 1.4% [1.2%, 1.7%] |
| 0.1% | survival model, context only (no SMART) | 0.3% [0.1%, 0.6%] | 0.3% [0.2%, 0.4%] |
| 0.1% | 30-day yes/no classifier (SMART + context) | 52.2% [49.9%, 54.8%] | 2.1% [1.8%, 2.4%] |
| 0.1% | rule: critical SMART counters (5, 187, 197, 198) | 31.5% [29.8%, 33.7%] | 0.8% [0.6%, 0.9%] |
| 0.1% | survival model, SMART + context, recalibrated on the last year | 46.4% [44.3%, 48.9%] | 1.4% [1.2%, 1.7%] |
| 0.3% | survival model, SMART + context | 61.7% [59.6%, 64.0%] | 3.8% [3.4%, 4.2%] |
| 0.3% | survival model, context only (no SMART) | 2.0% [1.4%, 2.7%] | 0.7% [0.5%, 0.8%] |
| 0.3% | 30-day yes/no classifier (SMART + context) | 63.4% [61.2%, 65.7%] | 4.1% [3.7%, 4.5%] |
| 0.3% | rule: critical SMART counters (5, 187, 197, 198) | 40.9% [38.5%, 43.1%] | 1.4% [1.1%, 1.6%] |
| 0.3% | survival model, SMART + context, recalibrated on the last year | 61.6% [59.5%, 63.9%] | 3.8% [3.4%, 4.2%] |
| 1.0% | survival model, SMART + context | 72.3% [70.1%, 74.3%] | 7.9% [7.3%, 8.5%] |
| 1.0% | survival model, context only (no SMART) | 7.7% [6.5%, 9.1%] | 10.4% [9.8%, 11.2%] |
| 1.0% | 30-day yes/no classifier (SMART + context) | 73.7% [71.6%, 75.8%] | 13.6% [12.9%, 14.5%] |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 52.7% [50.3%, 54.9%] | 2.4% [2.1%, 2.8%] |
| 1.0% | survival model, SMART + context, recalibrated on the last year | 72.3% [70.0%, 74.2%] | 7.9% [7.3%, 8.5%] |

At the same share of non-failing drives alerted (each model's threshold set on test for that share, a point on a drive-level ROC curve):

| non-failing drives alerted | model | failing drives caught | difference vs the rule (paired) |
|---|---|---|---|
| 0.99% | survival model, SMART + context | 37.1% [32.7%, 43.6%] | 2.7% [-1.7%, 7.5%] |
| 0.68% | survival model, context only (no SMART) | 2.2% [1.5%, 2.9%] | -32.3% [-37.2%, -28.7%] |
| 0.99% | 30-day yes/no classifier (SMART + context) | 34.1% [30.0%, 40.7%] | -0.3% [-4.9%, 4.0%] |
| 0.99% | rule: critical SMART counters (5, 187, 197, 198) | 34.4% [31.1%, 39.3%] | - |
| 0.99% | survival model, SMART + context, recalibrated on the last year | 37.3% [32.7%, 43.2%] | 2.9% [-1.7%, 7.5%] |
| 2.49% | survival model, SMART + context | 55.3% [52.5%, 58.7%] | 2.2% [-0.8%, 5.8%] |
| 2.31% | survival model, context only (no SMART) | 3.2% [1.8%, 4.3%] | -49.9% [-53.1%, -45.0%] |
| 2.49% | 30-day yes/no classifier (SMART + context) | 56.2% [52.5%, 59.0%] | 3.1% [0.0%, 6.5%] |
| 2.49% | rule: critical SMART counters (5, 187, 197, 198) | 53.1% [48.5%, 56.1%] | - |
| 2.49% | survival model, SMART + context, recalibrated on the last year | 55.3% [52.4%, 58.7%] | 2.2% [-0.8%, 5.8%] |
| 4.99% | survival model, SMART + context | 66.9% [64.8%, 69.0%] | -1.5% [-3.6%, 2.6%] |
| 2.67% | survival model, context only (no SMART) | 3.4% [2.5%, 4.4%] | -65.0% [-67.4%, -59.8%] |
| 4.99% | 30-day yes/no classifier (SMART + context) | 66.3% [63.9%, 69.0%] | -2.2% [-3.8%, 1.9%] |
| 4.97% | rule: critical SMART counters (5, 187, 197, 198) | 68.4% [63.5%, 70.7%] | - |
| 4.99% | survival model, SMART + context, recalibrated on the last year | 67.0% [64.8%, 69.2%] | -1.4% [-3.5%, 2.6%] |

**First alert, any lead time.** Each drive counted once over the test period; a failing drive (1770) is caught if any weekly check before its failure alerts. Thresholds set on test for each share; lead = days from the first alert to the failure (quartiles).

| non-failing drives alerted | model | failing drives caught | difference vs the rule (paired) | lead days (25/50/75%) | first alert within 30 days |
|---|---|---|---|---|---|
| 0.99% | survival model, SMART + context | 42.3% [37.1%, 49.4%] | 7.3% [2.4%, 12.9%] | 12/40/111 | 42.3% |
| 0.68% | survival model, context only (no SMART) | 2.6% [1.9%, 3.4%] | -32.4% [-37.3%, -28.8%] | 99/155/311 | 2.2% |
| 0.99% | 30-day yes/no classifier (SMART + context) | 38.5% [34.0%, 45.9%] | 3.4% [-0.9%, 8.8%] | 9/30/97 | 49.3% |
| 0.99% | rule: critical SMART counters (5, 187, 197, 198) | 35.0% [31.8%, 39.8%] | - | 14/50/154 | 36.9% |
| 0.99% | survival model, SMART + context, recalibrated on the last year | 42.4% [37.3%, 49.7%] | 7.3% [2.4%, 12.5%] | 12/40/112 | 42.4% |
| 2.49% | survival model, SMART + context | 61.3% [58.5%, 64.4%] | 7.9% [5.1%, 11.2%] | 22/75/165 | 31.4% |
| 2.31% | survival model, context only (no SMART) | 3.7% [2.3%, 4.9%] | -49.7% [-53.0%, -45.1%] | 72/162/282 | 13.6% |
| 2.49% | 30-day yes/no classifier (SMART + context) | 61.5% [57.8%, 64.5%] | 8.1% [4.9%, 11.3%] | 21/70/161 | 32.3% |
| 2.49% | rule: critical SMART counters (5, 187, 197, 198) | 53.4% [49.1%, 56.7%] | - | 25/90/217 | 28.1% |
| 2.49% | survival model, SMART + context, recalibrated on the last year | 61.3% [58.5%, 64.4%] | 7.9% [4.9%, 11.1%] | 22/75/165 | 31.4% |
| 4.99% | survival model, SMART + context | 72.4% [69.8%, 74.5%] | 3.4% [1.6%, 7.5%] | 31/105/226 | 24.2% |
| 2.67% | survival model, context only (no SMART) | 3.8% [2.8%, 4.9%] | -65.1% [-67.8%, -60.2%] | 74/164/280 | 10.3% |
| 4.99% | 30-day yes/no classifier (SMART + context) | 71.4% [68.9%, 73.8%] | 2.4% [0.9%, 6.3%] | 29/100/223 | 25.1% |
| 4.97% | rule: critical SMART counters (5, 187, 197, 198) | 68.9% [63.9%, 71.2%] | - | 35/124/268 | 22.5% |
| 4.99% | survival model, SMART + context, recalibrated on the last year | 72.4% [69.9%, 74.5%] | 3.5% [1.6%, 7.6%] | 31/106/227 | 24.3% |

**Per drive and quarter.** The unit is a drive in one quarter: a non-failing unit (53669) is alerted if a weekly check in that quarter fires; a failing drive (1766) is caught on its weekly checks in its last 30 days. Thresholds set on test for each share:

| non-failing units alerted | model | failing drives caught | difference vs the rule (paired) |
|---|---|---|---|
| 1.00% | survival model, SMART + context | 56.9% [53.6%, 59.7%] | 14.2% [10.6%, 17.5%] |
| 0.95% | survival model, context only (no SMART) | 2.8% [2.1%, 4.1%] | -39.9% [-43.6%, -36.0%] |
| 1.00% | 30-day yes/no classifier (SMART + context) | 56.2% [52.7%, 59.5%] | 13.5% [10.3%, 16.8%] |
| 1.00% | rule: critical SMART counters (5, 187, 197, 198) | 42.7% [38.9%, 46.3%] | - |
| 1.00% | survival model, SMART + context, recalibrated on the last year | 56.9% [53.6%, 59.7%] | 14.2% [10.6%, 17.5%] |
| 2.50% | survival model, SMART + context | 68.6% [66.5%, 71.0%] | 9.6% [6.5%, 13.1%] |
| 2.49% | survival model, context only (no SMART) | 5.6% [4.6%, 6.9%] | -53.3% [-57.0%, -49.0%] |
| 2.50% | 30-day yes/no classifier (SMART + context) | 69.4% [67.1%, 71.8%] | 10.4% [7.3%, 13.7%] |
| 2.50% | rule: critical SMART counters (5, 187, 197, 198) | 58.9% [54.9%, 62.7%] | - |
| 2.50% | survival model, SMART + context, recalibrated on the last year | 68.6% [66.5%, 71.0%] | 9.6% [6.5%, 13.0%] |
| 5.00% | survival model, SMART + context | 75.5% [73.2%, 77.6%] | 4.6% [2.3%, 7.4%] |
| 4.58% | survival model, context only (no SMART) | 9.2% [7.9%, 10.8%] | -61.6% [-65.1%, -57.6%] |
| 5.00% | 30-day yes/no classifier (SMART + context) | 75.0% [72.7%, 77.3%] | 4.1% [1.9%, 7.0%] |
| 4.87% | rule: critical SMART counters (5, 187, 197, 198) | 70.8% [67.4%, 74.0%] | - |
| 5.00% | survival model, SMART + context, recalibrated on the last year | 75.5% [73.2%, 77.6%] | 4.6% [2.3%, 7.4%] |

Share of the alerted non-failing quarter-units that belong to drives failing later, and the comparison with those units left out (5139 units, 1.05% of the negative weight):

| non-failing units alerted | model | alerts on later failures | failing drives caught without them | difference vs the rule |
|---|---|---|---|---|
| 1.0% | survival model, SMART + context | 20.0% | 59.5% [57.3%, 62.1%] | 14.1% [10.3%, 17.6%] |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 14.9% | 45.4% [41.0%, 49.3%] | - |
| 2.5% | survival model, SMART + context | 13.4% | 70.4% [67.9%, 73.4%] | 9.2% [6.9%, 11.7%] |
| 2.5% | rule: critical SMART counters (5, 187, 197, 198) | 11.4% | 61.2% [57.4%, 64.4%] | - |
| 5.0% | survival model, SMART + context | 8.1% | 75.7% [73.6%, 77.8%] | 3.5% [0.5%, 6.4%] |
| 5.0% | rule: critical SMART counters (5, 187, 197, 198) | 8.2% | 72.1% [68.8%, 75.6%] | - |

**Per drive and year.** The unit is a drive in one year: a non-failing unit (13850) is alerted if a weekly check in that year fires; a failing drive (1766) is caught on its weekly checks in its last 30 days. Thresholds set on test for each share:

| non-failing units alerted | model | failing drives caught | difference vs the rule (paired) |
|---|---|---|---|
| 1.00% | survival model, SMART + context | 45.3% [41.7%, 49.1%] | 8.0% [3.3%, 10.4%] |
| 0.69% | survival model, context only (no SMART) | 2.2% [1.5%, 2.9%] | -35.2% [-40.5%, -32.6%] |
| 1.00% | 30-day yes/no classifier (SMART + context) | 43.1% [39.0%, 48.3%] | 5.8% [1.1%, 8.8%] |
| 0.99% | rule: critical SMART counters (5, 187, 197, 198) | 37.3% [34.7%, 42.7%] | - |
| 1.00% | survival model, SMART + context, recalibrated on the last year | 45.3% [41.7%, 49.1%] | 8.0% [3.3%, 10.5%] |
| 2.49% | survival model, SMART + context | 60.4% [58.3%, 63.4%] | 5.3% [1.0%, 7.8%] |
| 1.79% | survival model, context only (no SMART) | 3.4% [2.5%, 4.4%] | -51.8% [-56.7%, -48.3%] |
| 2.50% | 30-day yes/no classifier (SMART + context) | 60.1% [57.4%, 63.4%] | 4.9% [1.2%, 7.5%] |
| 2.46% | rule: critical SMART counters (5, 187, 197, 198) | 55.2% [52.1%, 60.3%] | - |
| 2.49% | survival model, SMART + context, recalibrated on the last year | 60.5% [58.2%, 63.4%] | 5.3% [1.1%, 7.8%] |
| 5.00% | survival model, SMART + context | 69.3% [67.0%, 72.6%] | 0.6% [-1.3%, 3.1%] |
| 4.93% | survival model, context only (no SMART) | 5.6% [4.6%, 6.9%] | -63.1% [-66.2%, -59.7%] |
| 5.00% | 30-day yes/no classifier (SMART + context) | 70.3% [67.9%, 72.7%] | 1.6% [-1.0%, 3.4%] |
| 4.81% | rule: critical SMART counters (5, 187, 197, 198) | 68.7% [65.9%, 72.1%] | - |
| 5.00% | survival model, SMART + context, recalibrated on the last year | 69.3% [67.0%, 72.6%] | 0.6% [-1.3%, 3.1%] |

Share of the alerted non-failing year-units that belong to drives failing later, and the comparison with those units left out (721 units, 0.55% of the negative weight):

| non-failing units alerted | model | alerts on later failures | failing drives caught without them | difference vs the rule |
|---|---|---|---|---|
| 1.0% | survival model, SMART + context | 10.5% | 47.3% [43.1%, 51.0%] | 8.8% [3.3%, 10.8%] |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 8.3% | 38.6% [35.8%, 44.5%] | - |
| 2.5% | survival model, SMART + context | 7.3% | 61.2% [58.8%, 64.9%] | 3.9% [0.8%, 7.3%] |
| 2.5% | rule: critical SMART counters (5, 187, 197, 198) | 6.2% | 57.3% [53.2%, 61.9%] | - |
| 5.0% | survival model, SMART + context | 4.6% | 70.4% [67.7%, 73.3%] | 1.6% [-1.9%, 3.4%] |
| 5.0% | rule: critical SMART counters (5, 187, 197, 198) | 4.8% | 68.7% [66.8%, 72.9%] | - |

**Any critical counter above zero** (a simplified proxy of the operator's use, the rule's score > 0): 6.9% [6.3%, 7.4%] of non-failing drives alerted; failing drives caught 75.3% [73.1%, 77.3%] (last 30 days) and 75.8% [73.7%, 77.7%] (any lead). Models at the same share of non-failing drives alerted:

| failing drives counted | model | failing drives caught | difference vs the rule (paired) |
|---|---|---|---|
| last 30 days | 30-day yes/no classifier (SMART + context) | 70.1% | -5.2% [-6.8%, -3.9%] |
| last 30 days | survival model, SMART without counters 5/187/188/197/198 | 41.1% | -34.1% [-37.1%, -31.8%] |
| last 30 days | survival model, context only (no SMART) | 5.4% | -69.9% [-72.3%, -67.3%] |
| last 30 days | survival model, SMART + context | 68.8% | -6.5% [-7.9%, -4.6%] |
| last 30 days | survival model, SMART + context, recalibrated on the last year | 68.8% | -6.5% [-7.9%, -4.6%] |
| last 30 days | survival model, SMART + context, weight power 0.75 | 74.7% | -0.5% [-1.5%, 0.4%] |
| last 30 days | survival model, SMART + context, weight power 1.0 | 75.1% | -0.2% [-1.4%, 0.7%] |
| last 30 days | survival model, context + usage counters | 8.1% | -67.2% [-69.9%, -64.5%] |
| last 30 days | binary_30d_seed1 | 70.8% | -4.4% [-5.9%, -3.1%] |
| last 30 days | binary_30d_seed2 | 70.7% | -4.6% [-5.9%, -3.2%] |
| last 30 days | binary_30d_seed3 | 70.2% | -5.1% [-7.1%, -3.8%] |
| last 30 days | binary_30d_seed4 | 70.2% | -5.0% [-6.5%, -3.5%] |
| last 30 days | hazard_smart_seed1 | 67.2% | -8.0% [-10.6%, -6.1%] |
| last 30 days | hazard_smart_seed2 | 67.3% | -8.0% [-11.0%, -6.0%] |
| last 30 days | hazard_smart_seed3 | 66.6% | -8.7% [-10.5%, -6.3%] |
| last 30 days | hazard_smart_seed4 | 68.3% | -7.0% [-8.3%, -5.5%] |
| last 30 days | hazard_smart_w075_seed1 | 75.1% | -0.1% [-1.2%, 0.7%] |
| last 30 days | hazard_smart_w075_seed2 | 75.3% | 0.0% [-1.4%, 0.8%] |
| last 30 days | hazard_smart_w075_seed3 | 75.5% | 0.2% [-0.9%, 1.0%] |
| last 30 days | hazard_smart_w075_seed4 | 75.4% | 0.1% [-1.0%, 0.9%] |
| any lead | 30-day yes/no classifier (SMART + context) | 74.7% | -1.0% [-2.4%, 0.1%] |
| any lead | survival model, SMART without counters 5/187/188/197/198 | 44.8% | -31.0% [-34.0%, -28.5%] |
| any lead | survival model, context only (no SMART) | 7.2% | -68.6% [-72.0%, -65.9%] |
| any lead | survival model, SMART + context | 74.1% | -1.7% [-2.8%, -0.5%] |
| any lead | survival model, SMART + context, recalibrated on the last year | 74.1% | -1.7% [-2.8%, -0.5%] |
| any lead | survival model, SMART + context, weight power 0.75 | 76.7% | 1.0% [0.0%, 1.7%] |
| any lead | survival model, SMART + context, weight power 1.0 | 76.9% | 1.1% [0.1%, 1.9%] |
| any lead | survival model, context + usage counters | 9.0% | -66.7% [-69.1%, -63.9%] |
| any lead | binary_30d_seed1 | 75.4% | -0.4% [-1.7%, 0.6%] |
| any lead | binary_30d_seed2 | 74.9% | -0.9% [-1.9%, 0.3%] |
| any lead | binary_30d_seed3 | 74.7% | -1.0% [-2.5%, 0.0%] |
| any lead | binary_30d_seed4 | 75.0% | -0.7% [-2.0%, 0.3%] |
| any lead | hazard_smart_seed1 | 73.1% | -2.7% [-4.9%, -1.2%] |
| any lead | hazard_smart_seed2 | 72.6% | -3.2% [-5.4%, -1.5%] |
| any lead | hazard_smart_seed3 | 72.5% | -3.2% [-4.6%, -1.0%] |
| any lead | hazard_smart_seed4 | 73.4% | -2.3% [-3.4%, -1.0%] |
| any lead | hazard_smart_w075_seed1 | 76.8% | 1.1% [0.2%, 1.8%] |
| any lead | hazard_smart_w075_seed2 | 76.8% | 1.0% [0.1%, 1.8%] |
| any lead | hazard_smart_w075_seed3 | 77.1% | 1.3% [0.4%, 2.1%] |
| any lead | hazard_smart_w075_seed4 | 77.1% | 1.3% [0.4%, 2.0%] |

**Seed replicates.** Per-drive difference vs the rule (percentage points) of hazard_smart and its seed replicates, at the same share of non-failing units alerted:

| count | non-failing alerted | seeds | difference range | intervals above zero | intervals below zero |
|---|---|---|---|---|---|
| whole period, last 30 days | 1.0% | 5 | +0.8 to +4.1 | 0 of 5 | 0 of 5 |
| whole period, last 30 days | 2.5% | 5 | +1.2 to +2.4 | 0 of 5 | 0 of 5 |
| whole period, last 30 days | 5.0% | 5 | -6.1 to -1.5 | 0 of 5 | 3 of 5 |
| whole period, any lead | 1.0% | 5 | +4.8 to +7.9 | 4 of 5 | 0 of 5 |
| whole period, any lead | 2.5% | 5 | +6.3 to +7.9 | 5 of 5 | 0 of 5 |
| whole period, any lead | 5.0% | 5 | -0.3 to +3.4 | 2 of 5 | 0 of 5 |
| quarter | 1.0% | 5 | +12.3 to +14.2 | 5 of 5 | 0 of 5 |
| quarter | 2.5% | 5 | +8.7 to +9.6 | 5 of 5 | 0 of 5 |
| quarter | 5.0% | 5 | +4.0 to +4.6 | 5 of 5 | 0 of 5 |
| year | 1.0% | 5 | +7.7 to +8.8 | 5 of 5 | 0 of 5 |
| year | 2.5% | 5 | +3.6 to +5.7 | 4 of 5 | 0 of 5 |
| year | 5.0% | 5 | -0.8 to +0.6 | 0 of 5 | 0 of 5 |

![detection](detection.png)

## Calibration

Mean predicted failure probability vs the Kaplan-Meier observed share, by decile of predicted risk. Points on the diagonal mean that a predicted 5% really fails 5% of the time.

![calibration](calibration.png)

**Calibration over time** (mean predicted vs observed risk of failing within 30 days; ratio = predicted / observed with a 95% drive bootstrap). Validation drives are from the training era, test from 2024 on. A gap that appears only in the test years is drift. "Outside band" = the test year's ratio is outside the range of the validation-year ratios. Reference = survival model, SMART + context; recalibrated = survival model, SMART + context, recalibrated on the last year.

| split | year | snapshots | observed | predicted (reference) | ratio (reference) | outside band (reference) | predicted (recalibrated) | ratio (recalibrated) | outside band (recalibrated) |
|---|---|---|---|---|---|---|---|---|---|
| val | 2016 | 70518 | 0.162% | 0.183% | 1.13 [0.94, 1.37] | - | 0.222% | 1.37 [1.15, 1.67] | - |
| val | 2017 | 85198 | 0.154% | 0.162% | 1.05 [0.86, 1.30] | - | 0.196% | 1.27 [1.04, 1.58] | - |
| val | 2018 | 102268 | 0.134% | 0.127% | 0.95 [0.81, 1.10] | - | 0.153% | 1.14 [0.98, 1.33] | - |
| val | 2019 | 116101 | 0.165% | 0.150% | 0.91 [0.72, 1.16] | - | 0.182% | 1.10 [0.88, 1.41] | - |
| val | 2020 | 137012 | 0.084% | 0.116% | 1.38 [1.14, 1.73] | - | 0.140% | 1.67 [1.38, 2.10] | - |
| val | 2021 | 169154 | 0.088% | 0.100% | 1.13 [0.98, 1.31] | - | 0.121% | 1.37 [1.18, 1.59] | - |
| val | 2022 | 191823 | 0.109% | 0.127% | 1.17 [1.03, 1.34] | - | 0.153% | 1.41 [1.25, 1.62] | - |
| val | 2023 | 205355 | 0.166% | 0.143% | 0.86 [0.77, 0.97] | - | 0.173% | 1.04 [0.93, 1.17] | - |
| test | 2024 | 422201 | 0.133% | 0.157% | 1.18 [1.09, 1.28] | no | 0.190% | 1.42 [1.31, 1.55] | no |
| test | 2025 | 403120 | 0.103% | 0.225% | 2.18 [1.89, 2.51] | yes | 0.273% | 2.64 [2.30, 3.04] | yes |

- survival model, SMART + context: predicted/observed ratio over validation years spans 0.86 to 1.38. The last validation year (2023, ratio 0.86) is outside the band of the earlier validation years, an early sign of drift that needs no test data. Test years outside the band: 2025.
- survival model, SMART + context, recalibrated on the last year: predicted/observed ratio over validation years spans 1.04 to 1.67. The last validation year (2023, ratio 1.04) is outside the band of the earlier validation years, an early sign of drift that needs no test data. Test years outside the band: 2025.

## Retirement

Drives that never fail and have snapshots in a year, split into those that stop reporting before the end of the next year (left) and those still reporting (stayed). The survival estimates assume that leaving is unrelated to health; then both groups would carry about the same predicted risk. A ratio above 1 means the drives that leave already looked riskier beforehand. That suggests censoring is informative (some drives may be retired before they would have failed). If so, the observed failure risk is too low, by an amount this check cannot measure: it does not say how many of them would have failed. The alert threshold is the main-budget threshold of survival model, SMART + context.

| split | year | drives left | drives stayed | mean predicted 30-day risk, left | mean predicted 30-day risk, stayed | ratio left/stayed | above alert threshold, left | above alert threshold, stayed |
|---|---|---|---|---|---|---|---|---|
| val | 2016 | 170 | 538 | 0.141% | 0.160% | 0.88 | 1.12% | 0.73% |
| val | 2017 | 280 | 672 | 0.265% | 0.083% | 3.17 | 1.78% | 0.12% |
| val | 2018 | 236 | 869 | 0.187% | 0.070% | 2.66 | 0.60% | 0.16% |
| val | 2019 | 233 | 964 | 0.136% | 0.108% | 1.26 | 0.28% | 0.79% |
| val | 2020 | 357 | 1270 | 0.138% | 0.060% | 2.31 | 1.20% | 0.36% |
| val | 2021 | 202 | 1828 | 0.115% | 0.056% | 2.05 | 1.11% | 0.25% |
| val | 2022 | 101 | 2040 | 0.165% | 0.065% | 2.52 | 3.22% | 0.46% |
| val | 2023 | 282 | 2383 | 0.173% | 0.075% | 2.31 | 2.77% | 0.64% |
| test | 2024 | 509 | 5809 | 0.203% | 0.100% | 2.02 | 2.16% | 1.08% |

The ratio is above 1 in 8 of 9 split-years with drives in both groups (no intervals: read it as a direction, not a test).

## Full follow-up

The main estimator keeps every snapshot whose status at the horizon is known, so failures near the panel's end count while healthy snapshots of the same days drop out. Here only snapshots dated at least H - 1 days before the panel's last day count, for positives and negatives alike (drives retired inside the horizon are still dropped). Gain = reference minus the model in the row, paired.

| horizon | model | snapshots up to | positive share | observed (Kaplan-Meier) | ROC-AUC | ROC-AUC, main estimator | PR-AUC | ROC-AUC gain of survival model, SMART + context |
|---|---|---|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 2025-12-25 | 0.027% | 0.027% | 0.905 [0.895, 0.914] | 0.905 | 0.0650 [0.0534, 0.0816] | - |
| 7 d | survival model, context only (no SMART) | 2025-12-25 | 0.027% | 0.027% | 0.603 [0.590, 0.617] | 0.603 | 0.0004 [0.0004, 0.0005] | +0.302 [0.284, 0.316] |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 2025-12-25 | 0.027% | 0.027% | 0.853 [0.842, 0.864] | 0.853 | 0.0295 [0.0225, 0.0400] | +0.052 [0.045, 0.060] |
| 30 d | survival model, SMART + context | 2025-12-02 | 0.120% | 0.120% | 0.877 [0.865, 0.885] | 0.877 | 0.1229 [0.1043, 0.1461] | - |
| 30 d | survival model, context only (no SMART) | 2025-12-02 | 0.120% | 0.120% | 0.603 [0.589, 0.616] | 0.603 | 0.0019 [0.0017, 0.0021] | +0.273 [0.260, 0.291] |
| 30 d | 30-day yes/no classifier (SMART + context) | 2025-12-02 | 0.120% | 0.120% | 0.878 [0.868, 0.885] | 0.878 | 0.1175 [0.1006, 0.1368] | -0.001 [-0.004, 0.002] |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 2025-12-02 | 0.120% | 0.120% | 0.824 [0.813, 0.833] | 0.823 | 0.0515 [0.0403, 0.0709] | +0.053 [0.045, 0.060] |
| 90 d | survival model, SMART + context | 2025-10-03 | 0.375% | 0.373% | 0.842 [0.831, 0.854] | 0.843 | 0.1744 [0.1513, 0.2032] | - |
| 90 d | survival model, context only (no SMART) | 2025-10-03 | 0.375% | 0.373% | 0.608 [0.594, 0.622] | 0.609 | 0.0056 [0.0052, 0.0062] | +0.234 [0.219, 0.252] |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 2025-10-03 | 0.375% | 0.373% | 0.785 [0.775, 0.798] | 0.786 | 0.0854 [0.0710, 0.1120] | +0.056 [0.048, 0.065] |
| 180 d | survival model, SMART + context | 2025-07-05 | 0.771% | 0.764% | 0.809 [0.796, 0.821] | 0.813 | 0.1915 [0.1696, 0.2197] | - |
| 180 d | survival model, context only (no SMART) | 2025-07-05 | 0.771% | 0.764% | 0.606 [0.592, 0.619] | 0.606 | 0.0114 [0.0106, 0.0124] | +0.203 [0.188, 0.216] |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 2025-07-05 | 0.771% | 0.764% | 0.753 [0.742, 0.763] | 0.755 | 0.1125 [0.0939, 0.1346] | +0.056 [0.048, 0.065] |
| 365 d | survival model, SMART + context | 2025-01-01 | 1.586% | 1.561% | 0.771 [0.758, 0.786] | 0.787 | 0.2298 [0.2062, 0.2590] | - |
| 365 d | survival model, context only (no SMART) | 2025-01-01 | 1.586% | 1.561% | 0.590 [0.576, 0.605] | 0.585 | 0.0221 [0.0202, 0.0243] | +0.182 [0.166, 0.196] |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 2025-01-01 | 1.586% | 1.561% | 0.712 [0.701, 0.722] | 0.722 | 0.1540 [0.1323, 0.1821] | +0.060 [0.050, 0.071] |

## Calibration by group

Predicted / observed 30-day risk of survival model, SMART + context by part of the fleet, for the last validation year and the test years (95% drive bootstrap). Weight share = the group's share of the year's weighted snapshots.

| split | year | group | weight share | failing drives | observed | predicted | ratio |
|---|---|---|---|---|---|---|---|
| val | 2023 | all | n/a | 489 | 0.166% | 0.143% | 0.86 [0.77, 0.97] |
| val | 2023 | capacity < 16 TB | 71.4% | 438 | 0.208% | 0.175% | 0.84 [0.75, 0.96] |
| val | 2023 | capacity >= 16 TB | 28.6% | 51 | 0.060% | 0.063% | 1.05 [0.84, 1.56] |
| val | 2023 | in service 2-4 years | 40.5% | 239 | 0.180% | 0.144% | 0.80 [0.70, 0.95] |
| val | 2023 | in service < 2 years | 32.6% | 103 | 0.058% | 0.058% | 0.99 [0.79, 1.32] |
| val | 2023 | in service < 2 years, other models | 0.4% | 8 | 0.259% | 0.207% | 0.80 [0.33, 3.38] |
| val | 2023 | in service < 2 years, training models | 32.3% | 95 | 0.056% | 0.056% | 1.00 [0.76, 1.31] |
| val | 2023 | in service >= 4 years | 26.9% | 224 | 0.277% | 0.245% | 0.89 [0.73, 1.05] |
| val | 2023 | model MG08ACA16TEY | 2.2% | 6 | 0.089% | 0.060% | 0.68 [0.39, 2.18] |
| val | 2023 | other models | 1.4% | 21 | 0.514% | 0.395% | 0.77 [0.45, 1.32] |
| val | 2023 | training models | 98.6% | 468 | 0.161% | 0.140% | 0.87 [0.79, 0.97] |
| val | 2023 | vendor HGST | 15.7% | 72 | 0.154% | 0.100% | 0.65 [0.44, 1.02] |
| val | 2023 | vendor Seagate | 46.6% | 317 | 0.231% | 0.200% | 0.87 [0.77, 0.97] |
| val | 2023 | vendor Toshiba | 26.5% | 86 | 0.111% | 0.111% | 1.00 [0.76, 1.37] |
| val | 2023 | vendor Toshiba without MG08ACA16TEY | 24.4% | 80 | 0.113% | 0.116% | 1.02 [0.81, 1.37] |
| val | 2023 | vendor WDC | 11.2% | 14 | 0.043% | 0.042% | 0.98 [0.59, 2.02] |
| test | 2024 | all | n/a | 1739 | 0.133% | 0.157% | 1.18 [1.09, 1.28] |
| test | 2024 | capacity < 16 TB | 56.0% | 1250 | 0.182% | 0.208% | 1.15 [1.06, 1.29] |
| test | 2024 | capacity >= 16 TB | 44.0% | 489 | 0.072% | 0.092% | 1.27 [1.07, 1.51] |
| test | 2024 | in service 2-4 years | 38.0% | 754 | 0.110% | 0.109% | 1.00 [0.86, 1.14] |
| test | 2024 | in service < 2 years | 34.1% | 417 | 0.079% | 0.091% | 1.15 [0.98, 1.39] |
| test | 2024 | in service < 2 years, other models | 1.1% | 29 | 0.118% | 0.323% | 2.74 [1.36, 5.77] |
| test | 2024 | in service < 2 years, training models | 33.0% | 388 | 0.078% | 0.083% | 1.07 [0.88, 1.28] |
| test | 2024 | in service >= 4 years | 27.9% | 871 | 0.233% | 0.302% | 1.30 [1.13, 1.47] |
| test | 2024 | model MG08ACA16TEY | 1.5% | 74 | 0.153% | 0.093% | 0.60 [0.37, 1.12] |
| test | 2024 | other models | 1.9% | 48 | 0.166% | 0.271% | 1.63 [1.06, 2.93] |
| test | 2024 | training models | 98.1% | 1691 | 0.133% | 0.155% | 1.16 [1.05, 1.28] |
| test | 2024 | vendor HGST | 12.8% | 379 | 0.245% | 0.205% | 0.83 [0.64, 1.03] |
| test | 2024 | vendor Seagate | 38.0% | 738 | 0.157% | 0.222% | 1.41 [1.25, 1.59] |
| test | 2024 | vendor Toshiba | 32.1% | 477 | 0.100% | 0.123% | 1.24 [1.07, 1.45] |
| test | 2024 | vendor Toshiba without MG08ACA16TEY | 30.6% | 403 | 0.097% | 0.125% | 1.29 [1.11, 1.49] |
| test | 2024 | vendor WDC | 17.1% | 145 | 0.060% | 0.038% | 0.64 [0.51, 0.83] |
| test | 2025 | all | n/a | 850 | 0.103% | 0.225% | 2.18 [1.89, 2.51] |
| test | 2025 | capacity < 16 TB | 46.0% | 546 | 0.139% | 0.302% | 2.17 [1.84, 2.59] |
| test | 2025 | capacity >= 16 TB | 54.0% | 304 | 0.073% | 0.161% | 2.21 [1.83, 2.74] |
| test | 2025 | in service 2-4 years | 24.3% | 273 | 0.094% | 0.163% | 1.73 [1.40, 2.23] |
| test | 2025 | in service < 2 years | 34.8% | 182 | 0.055% | 0.170% | 3.10 [2.35, 3.97] |
| test | 2025 | in service < 2 years, other models | 6.8% | 44 | 0.088% | 0.354% | 4.01 [2.82, 5.50] |
| test | 2025 | in service < 2 years, training models | 28.0% | 138 | 0.047% | 0.125% | 2.67 [1.64, 4.00] |
| test | 2025 | in service >= 4 years | 40.8% | 519 | 0.151% | 0.310% | 2.05 [1.78, 2.43] |
| test | 2025 | model MG08ACA16TEY | 1.3% | 58 | 0.585% | 0.192% | 0.33 [0.18, 0.56] |
| test | 2025 | other models | 7.7% | 52 | 0.092% | 0.345% | 3.75 [2.81, 5.18] |
| test | 2025 | training models | 92.3% | 798 | 0.104% | 0.215% | 2.07 [1.79, 2.33] |
| test | 2025 | vendor HGST | 9.0% | 164 | 0.209% | 0.365% | 1.75 [1.29, 2.37] |
| test | 2025 | vendor Seagate | 34.9% | 335 | 0.115% | 0.342% | 2.97 [2.41, 3.59] |
| test | 2025 | vendor Toshiba | 32.7% | 264 | 0.103% | 0.176% | 1.71 [1.46, 2.02] |
| test | 2025 | vendor Toshiba without MG08ACA16TEY | 31.4% | 206 | 0.082% | 0.175% | 2.14 [1.85, 2.56] |
| test | 2025 | vendor WDC | 23.4% | 87 | 0.047% | 0.068% | 1.45 [0.99, 2.10] |

## Training variation (seeds)

The reference survival model and the 30-day classifier retrained with other seeds, all else equal. Point estimates on the known-status test snapshots.

| model | horizon | trainings | ROC-AUC min-max | ROC-AUC sd | PR-AUC min-max | PR-AUC sd |
|---|---|---|---|---|---|---|
| binary_30d | 30 d | 5 | 0.878-0.881 | 0.0013 | 0.1131-0.1233 | 0.0038 |
| hazard_smart | 7 d | 5 | 0.900-0.905 | 0.0017 | 0.0650-0.0710 | 0.0025 |
| hazard_smart | 30 d | 5 | 0.871-0.877 | 0.0023 | 0.1235-0.1287 | 0.0022 |
| hazard_smart | 90 d | 5 | 0.836-0.843 | 0.0030 | 0.1750-0.1821 | 0.0030 |
| hazard_smart | 180 d | 5 | 0.808-0.813 | 0.0022 | 0.2130-0.2194 | 0.0026 |
| hazard_smart | 365 d | 5 | 0.784-0.787 | 0.0016 | 0.3000-0.3117 | 0.0043 |
| hazard_smart_w075 | 7 d | 5 | 0.903-0.907 | 0.0018 | 0.0641-0.0738 | 0.0035 |
| hazard_smart_w075 | 30 d | 5 | 0.876-0.880 | 0.0018 | 0.1172-0.1281 | 0.0040 |
| hazard_smart_w075 | 90 d | 5 | 0.843-0.848 | 0.0023 | 0.1713-0.1823 | 0.0039 |
| hazard_smart_w075 | 180 d | 5 | 0.806-0.816 | 0.0037 | 0.1985-0.2042 | 0.0023 |
| hazard_smart_w075 | 365 d | 5 | 0.783-0.790 | 0.0024 | 0.2847-0.2966 | 0.0048 |

Survival minus classifier, per seed pair (seed 0 = the models above):

| seed | horizon | ROC-AUC difference | PR-AUC difference |
|---|---|---|---|
| 0 | 30 d | -0.0013 | 0.0053 |
| 1 | 30 d | -0.0090 | 0.0002 |
| 2 | 30 d | -0.0079 | 0.0156 |
| 3 | 30 d | -0.0059 | 0.0038 |
| 4 | 30 d | -0.0077 | 0.0053 |

## Validation discrimination

ROC-AUC and PR-AUC on the validation drives (2016-2023, known-status snapshots), without the test set: what a choice between variants, such as the training-weight exponent, would rest on. Point estimates.

| model | 7 d ROC-AUC / PR-AUC | 30 d ROC-AUC / PR-AUC | 90 d ROC-AUC / PR-AUC | 180 d ROC-AUC / PR-AUC | 365 d ROC-AUC / PR-AUC |
|---|---|---|---|---|---|
| survival model, SMART + context | 0.8886 / 0.1054 | 0.8659 / 0.1545 | 0.8409 / 0.1884 | 0.8243 / 0.2145 | 0.8060 / 0.2512 |
| survival model, context only (no SMART) | 0.7145 / 0.0013 | 0.7149 / 0.0050 | 0.7164 / 0.0148 | 0.7179 / 0.0266 | 0.7201 / 0.0545 |
| 30-day yes/no classifier (SMART + context) | - | 0.8674 / 0.1650 | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.8002 / 0.0307 | 0.7614 / 0.0620 | 0.7190 / 0.0977 | 0.6866 / 0.1245 | 0.6524 / 0.1532 |
| survival model, SMART without counters 5/187/188/197/198 | 0.8039 / 0.0281 | 0.7831 / 0.0353 | 0.7704 / 0.0459 | 0.7633 / 0.0619 | 0.7581 / 0.0967 |
| survival model, context + usage counters | 0.7292 / 0.0018 | 0.7307 / 0.0062 | 0.7354 / 0.0167 | 0.7372 / 0.0302 | 0.7404 / 0.0636 |
| survival model, SMART + context, weight power 0.75 | 0.8847 / 0.0972 | 0.8627 / 0.1509 | 0.8389 / 0.1896 | 0.8232 / 0.2141 | 0.8045 / 0.2484 |
| survival model, SMART + context, weight power 1.0 | 0.8816 / 0.0893 | 0.8602 / 0.1448 | 0.8371 / 0.1837 | 0.8217 / 0.2040 | 0.8035 / 0.2395 |
| survival model, SMART + context, recalibrated on the last year | 0.8886 / 0.1054 | 0.8659 / 0.1545 | 0.8409 / 0.1883 | 0.8243 / 0.2144 | 0.8060 / 0.2511 |
| binary_30d_seed1 | - | 0.8654 / 0.1613 | - | - | - |
| binary_30d_seed2 | - | 0.8675 / 0.1649 | - | - | - |
| binary_30d_seed3 | - | 0.8677 / 0.1636 | - | - | - |
| binary_30d_seed4 | - | 0.8662 / 0.1631 | - | - | - |
| hazard_smart_seed1 | 0.8905 / 0.1098 | 0.8675 / 0.1549 | 0.8421 / 0.1884 | 0.8255 / 0.2131 | 0.8077 / 0.2499 |
| hazard_smart_seed2 | 0.8895 / 0.1107 | 0.8669 / 0.1543 | 0.8418 / 0.1871 | 0.8248 / 0.2131 | 0.8068 / 0.2498 |
| hazard_smart_seed3 | 0.8897 / 0.1103 | 0.8667 / 0.1565 | 0.8415 / 0.1882 | 0.8248 / 0.2147 | 0.8071 / 0.2496 |
| hazard_smart_seed4 | 0.8893 / 0.1076 | 0.8666 / 0.1563 | 0.8412 / 0.1921 | 0.8246 / 0.2163 | 0.8068 / 0.2516 |
| hazard_smart_w075_seed1 | 0.8842 / 0.0969 | 0.8631 / 0.1502 | 0.8390 / 0.1861 | 0.8236 / 0.2115 | 0.8053 / 0.2476 |
| hazard_smart_w075_seed2 | 0.8824 / 0.0963 | 0.8617 / 0.1536 | 0.8387 / 0.1890 | 0.8235 / 0.2141 | 0.8047 / 0.2508 |
| hazard_smart_w075_seed3 | 0.8837 / 0.0971 | 0.8624 / 0.1538 | 0.8387 / 0.1876 | 0.8232 / 0.2103 | 0.8048 / 0.2471 |
| hazard_smart_w075_seed4 | 0.8840 / 0.0988 | 0.8626 / 0.1524 | 0.8391 / 0.1916 | 0.8236 / 0.2164 | 0.8050 / 0.2514 |

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

![importance](importance.png)

Also see `build/explore/km_by_counters.png` and `build/explore/models.csv`.


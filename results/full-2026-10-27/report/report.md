# Can SMART data predict when a hard drive will fail?

Scale **full**: 57309 drives in the cohort (failing drives sampled at 100%, healthy at 10.0%, weighted back to the real population). Test: 8981 drives never seen in training, 1784 of which fail during the test period (825321 snapshots). Verification gate: 29/30 checks passed.

## Answer

- **Do SMART metrics carry failure information?** Yes. Adding SMART to what is known without it (drive model, capacity, time in service) improves ROC-AUC at 5 of 5 horizons with a 95% interval that excludes zero:
  - 7 days: +0.300 [0.282, 0.314]
  - 30 days: +0.273 [0.260, 0.288]
  - 90 days: +0.241 [0.225, 0.259]
  - 180 days: +0.221 [0.208, 0.236]
  - 365 days: +0.211 [0.197, 0.228]
- **How much of that is the replacement policy?** Backblaze replaces drives when counters 5, 187, 188, 197 or 198 rise, so those counters partly define the failure label. The full model's ROC-AUC exceeds the model without them by +0.104 [0.096, 0.112] at 30 days (an interval above zero at 5 of 5 horizons). The SMART gain above is therefore an upper bound on what SMART adds beyond the operator's replacement policy.
- **How far ahead?** Ranking is strongest close to failure (ROC-AUC 0.906 for 7 days) and weaker for the long term (0.786 for 365 days; long horizons are measured on earlier test snapshots, see Discrimination by horizon).
- **But failures are rare.** Even within 7 days only 0.027% of drive-days fail. The model's PR-AUC there is 0.0674 (a random ranking would score about the base rate), so at any useful recall many alerts are false (see Early warning).
- **Is it more than the last days?** Counting as positives only snapshots >= 7 days before failure, the 30-day PR-AUC is 0.0788 [0.0661, 0.0970] against 0.1239 overall (base rate 0.093% vs 0.121%); ROC-AUC 0.868 [0.857, 0.877]. Much of the precision comes from the last days before failure.
- **Silent failures** (no critical counter above zero in any test snapshot): 368 of the 1784 failing test drives. On them the 30-day ROC-AUC of survival model, SMART + context is 0.639 [0.608, 0.666] against 0.876 [0.866, 0.885] overall: still above chance.
- **When will it probably fail?** When the model names a day within the next year, it is too pessimistic (drives fail later than predicted): 6.5% of drives failed by their predicted 10% day, 33.0% by the predicted median and 76.5% by the predicted 90% day (targets 10/50/90%). For drives that do fail within a year it names a median within a year only 16.9% of the time: most failures are not visible in SMART long in advance. For healthy drives it says "more than a year" 99.8% of the time.
- **One survival model or a dedicated 30-day classifier?** At 30 days the survival model's ROC-AUC minus the classifier's is -0.001 [-0.004, 0.002] (paired bootstrap), PR-AUC +0.0069 [-0.0056, 0.0176]; the survival model is not better in 72% of rounds. Neither ranks clearly better, and the survival model also covers the other horizons.
- **Against the classic rule** (log-sum of the reallocated, reported-uncorrectable, pending and offline-uncorrectable sector counters 5, 187, 197, 198), the model gains +0.053 ROC-AUC [0.046, 0.061] at 7 days.

## Discrimination by horizon

ROC-AUC and PR-AUC per drive-day snapshot, on test snapshots whose status at the horizon is known, weighted to real prevalence. Brackets: 95% drive-level bootstrap (200 rounds). Base rate = real share of drive-days that fail within the horizon. All 1784 failing test drives are positive at every horizon (each has snapshots close to its failure day), so the last column counts positive snapshots instead.

| horizon | model | ROC-AUC | PR-AUC | Brier | base rate | positive snapshots |
|---|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.906 [0.896, 0.915] | 0.0674 [0.0574, 0.0809] | 0.00027 | 0.027% | 11632 |
| 7 d | survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.0004 [0.0004, 0.0004] | 0.00027 | 0.027% | 11632 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0295 [0.0225, 0.0400] | n/a | 0.027% | 11632 |
| 30 d | survival model, SMART + context | 0.876 [0.866, 0.885] | 0.1239 [0.1061, 0.1473] | 0.00117 | 0.121% | 50334 |
| 30 d | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.00121 | 0.121% | 50334 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.877 [0.867, 0.885] | 0.1170 [0.1000, 0.1372] | 0.00127 | 0.121% | 50334 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | n/a | 0.121% | 50334 |
| 90 d | survival model, SMART + context | 0.843 [0.832, 0.855] | 0.1798 [0.1568, 0.2099] | 0.00358 | 0.388% | 145601 |
| 90 d | survival model, context only (no SMART) | 0.601 [0.586, 0.616] | 0.0054 [0.0050, 0.0058] | 0.00389 | 0.388% | 145601 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.786 [0.776, 0.798] | 0.0893 [0.0733, 0.1164] | n/a | 0.388% | 145601 |
| 180 d | survival model, SMART + context | 0.814 [0.804, 0.826] | 0.2191 [0.1956, 0.2478] | 0.00765 | 0.865% | 163747 |
| 180 d | survival model, context only (no SMART) | 0.593 [0.580, 0.605] | 0.0117 [0.0110, 0.0125] | 0.00865 | 0.865% | 163747 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.755 [0.744, 0.764] | 0.1295 [0.1095, 0.1524] | n/a | 0.865% | 163747 |
| 365 d | survival model, SMART + context | 0.786 [0.776, 0.800] | 0.3123 [0.2885, 0.3386] | 0.01830 | 2.272% | 189708 |
| 365 d | survival model, context only (no SMART) | 0.574 [0.560, 0.591] | 0.0305 [0.0280, 0.0340] | 0.02230 | 2.272% | 189708 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.722 [0.711, 0.732] | 0.2145 [0.1873, 0.2420] | n/a | 2.272% | 189708 |

A horizon of H days needs H days of follow-up to know that a drive survived it, so the longer the horizon, the earlier the test snapshots it can use. The 365-day row uses only snapshots from roughly the first test year (2024); longer horizons are measured on an earlier, different calendar cohort than the short ones, so the rows are not a like-for-like trend. Test snapshots with a known status (825321 in total): 7 d: 819135 snapshots, known-healthy ones dated up to 2025-12-25; 30 d: 795715 snapshots, known-healthy ones dated up to 2025-12-02; 90 d: 735702 snapshots, known-healthy ones dated up to 2025-10-03; 180 d: 650242 snapshots, known-healthy ones dated up to 2025-07-05; 365 d: 485740 snapshots, known-healthy ones dated up to 2025-01-01.

**Robustness.** The same ranking with inverse-probability-of-censoring weights (IPCW: snapshots whose status is unknown are represented by weighting up comparable known ones, instead of being dropped), and a drive-level ROC-AUC on one random snapshot per drive, weighted per drive (so drives with many snapshots do not dominate). Brier skill = 1 - Brier / Brier of always predicting the base rate; above 0 beats that constant.

| horizon | model | ROC-AUC, IPCW (per drive-day) | PR-AUC, IPCW (per drive-day) | ROC-AUC (per drive) | Brier skill |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context | 0.906 [0.896, 0.915] | 0.0671 [0.0571, 0.0805] | 0.901 [0.837, 0.940] | -0.012 |
| 7 d | survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.0004 [0.0004, 0.0004] | 0.632 [0.578, 0.680] | -0.000 |
| 7 d | rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.0294 [0.0224, 0.0399] | 0.827 [0.763, 0.866] | n/a |
| 30 d | survival model, SMART + context | 0.876 [0.866, 0.885] | 0.1210 [0.1036, 0.1441] | 0.862 [0.836, 0.888] | 0.027 |
| 30 d | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.626 [0.597, 0.650] | -0.002 |
| 30 d | 30-day yes/no classifier (SMART + context) | 0.877 [0.867, 0.884] | 0.1143 [0.0976, 0.1342] | 0.862 [0.838, 0.885] | -0.056 |
| 30 d | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0509 [0.0399, 0.0705] | 0.811 [0.785, 0.836] | n/a |
| 90 d | survival model, SMART + context | 0.841 [0.831, 0.854] | 0.1679 [0.1456, 0.1970] | 0.832 [0.818, 0.850] | 0.074 |
| 90 d | survival model, context only (no SMART) | 0.601 [0.586, 0.616] | 0.0050 [0.0047, 0.0054] | 0.624 [0.608, 0.643] | -0.007 |
| 90 d | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.774, 0.797] | 0.0825 [0.0675, 0.1088] | 0.782 [0.768, 0.799] | n/a |
| 180 d | survival model, SMART + context | 0.811 [0.800, 0.823] | 0.1890 [0.1672, 0.2161] | 0.832 [0.820, 0.847] | 0.108 |
| 180 d | survival model, context only (no SMART) | 0.593 [0.580, 0.605] | 0.0099 [0.0092, 0.0105] | 0.626 [0.610, 0.639] | -0.008 |
| 180 d | rule: critical SMART counters (5, 187, 197, 198) | 0.751 [0.740, 0.760] | 0.1094 [0.0915, 0.1308] | 0.778 [0.764, 0.791] | n/a |
| 365 d | survival model, SMART + context | 0.774 [0.763, 0.789] | 0.2323 [0.2101, 0.2574] | 0.829 [0.817, 0.846] | 0.176 |
| 365 d | survival model, context only (no SMART) | 0.575 [0.561, 0.593] | 0.0191 [0.0177, 0.0216] | 0.599 [0.585, 0.616] | -0.004 |
| 365 d | rule: critical SMART counters (5, 187, 197, 198) | 0.710 [0.699, 0.720] | 0.1497 [0.1253, 0.1765] | 0.768 [0.755, 0.781] | n/a |

![AUC by horizon](auc_by_horizon.png)

## Ablations and sensitivity

Each variant against the reference (survival model, SMART + context). Gain = reference minus variant, paired on the same bootstrap rounds; "not better" = share of rounds where the reference's ROC-AUC is not higher.

- **survival model, SMART without counters 5/187/188/197/198**: drops counters 5, 187, 188, 197 and 198 (raw, normalized and trends), the ones behind Backblaze's own replacement decisions. A drive replaced because these counters rose is recorded as failed, so part of the full model's SMART signal may be the replacement policy itself; the full model's gain over context only is an upper bound on what SMART adds beyond that policy.
- **survival model, context + usage counters**: context plus the usage counters only (4, 9, 12, 193, 240-242: power-on hours, start/stop and power cycles, load cycles, head flying hours, LBAs written and read). Tests whether SMART helps only because it measures age and wear.
- **survival model, SMART + context, weight power 0.75**: the reference features with training weights to the power 0.75 instead of 0.5. Tests how much the ranking depends on the weight exponent.
- **survival model, SMART + context, weight power 1.0**: the same with the full inverse-probability weights (power 1.0).
- **survival model, SMART + context, recalibrated on the last year**: the reference trees with probabilities recalibrated on the last validation year before the training cutoff. Tests whether a recent recalibration fixes drift (see Calibration over time); the trees are the same, so ranking changes only through the per-bin recalibration.

| horizon | model | ROC-AUC | reference gain, ROC-AUC | reference gain, PR-AUC | not better |
|---|---|---|---|---|---|
| 7 d | survival model, SMART + context (reference) | 0.906 [0.896, 0.915] |  |  |  |
| 7 d | survival model, SMART without counters 5/187/188/197/198 | 0.801 [0.790, 0.813] | +0.105 [0.096, 0.113] | +0.0449 [0.0335, 0.0566] | 0% |
| 7 d | survival model, context + usage counters | 0.654 [0.639, 0.667] | +0.251 [0.236, 0.264] | +0.0668 [0.0562, 0.0801] | 0% |
| 7 d | survival model, SMART + context, weight power 0.75 | 0.905 [0.896, 0.913] | +0.001 [-0.003, 0.004] | -0.0038 [-0.0131, 0.0050] | 34% |
| 7 d | survival model, SMART + context, weight power 1.0 | 0.904 [0.894, 0.912] | +0.002 [-0.002, 0.006] | +0.0075 [0.0004, 0.0149] | 12% |
| 7 d | survival model, SMART + context, recalibrated on the last year | 0.906 [0.896, 0.915] | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] | 100% |
| 30 d | survival model, SMART + context (reference) | 0.876 [0.866, 0.885] |  |  |  |
| 30 d | survival model, SMART without counters 5/187/188/197/198 | 0.772 [0.760, 0.786] | +0.104 [0.096, 0.112] | +0.0866 [0.0650, 0.1034] | 0% |
| 30 d | survival model, context + usage counters | 0.654 [0.641, 0.667] | +0.222 [0.211, 0.236] | +0.1216 [0.1038, 0.1450] | 0% |
| 30 d | survival model, SMART + context, weight power 0.75 | 0.880 [0.868, 0.888] | -0.003 [-0.007, 0.000] | -0.0017 [-0.0103, 0.0072] | 96% |
| 30 d | survival model, SMART + context, weight power 1.0 | 0.878 [0.869, 0.887] | -0.002 [-0.006, 0.000] | +0.0108 [0.0008, 0.0184] | 96% |
| 30 d | survival model, SMART + context, recalibrated on the last year | 0.876 [0.866, 0.885] | -0.000 [-0.000, -0.000] | -0.0001 [-0.0001, -0.0000] | 100% |
| 90 d | survival model, SMART + context (reference) | 0.843 [0.832, 0.855] |  |  |  |
| 90 d | survival model, SMART without counters 5/187/188/197/198 | 0.747 [0.732, 0.760] | +0.096 [0.087, 0.106] | +0.1259 [0.0990, 0.1555] | 0% |
| 90 d | survival model, context + usage counters | 0.654 [0.641, 0.667] | +0.188 [0.177, 0.204] | +0.1725 [0.1496, 0.2020] | 0% |
| 90 d | survival model, SMART + context, weight power 0.75 | 0.846 [0.835, 0.858] | -0.003 [-0.007, 0.001] | +0.0022 [-0.0061, 0.0124] | 93% |
| 90 d | survival model, SMART + context, weight power 1.0 | 0.848 [0.837, 0.860] | -0.006 [-0.009, -0.002] | +0.0093 [-0.0004, 0.0179] | 100% |
| 90 d | survival model, SMART + context, recalibrated on the last year | 0.843 [0.832, 0.855] | +0.000 [0.000, 0.000] | +0.0005 [0.0002, 0.0007] | 0% |
| 180 d | survival model, SMART + context (reference) | 0.814 [0.804, 0.826] |  |  |  |
| 180 d | survival model, SMART without counters 5/187/188/197/198 | 0.721 [0.709, 0.734] | +0.093 [0.084, 0.101] | +0.1464 [0.1195, 0.1718] | 0% |
| 180 d | survival model, context + usage counters | 0.653 [0.638, 0.665] | +0.161 [0.151, 0.175] | +0.2027 [0.1800, 0.2314] | 0% |
| 180 d | survival model, SMART + context, weight power 0.75 | 0.813 [0.801, 0.826] | +0.002 [-0.003, 0.006] | +0.0224 [0.0049, 0.0401] | 26% |
| 180 d | survival model, SMART + context, weight power 1.0 | 0.812 [0.801, 0.823] | +0.002 [-0.002, 0.008] | +0.0236 [0.0101, 0.0429] | 18% |
| 180 d | survival model, SMART + context, recalibrated on the last year | 0.815 [0.804, 0.826] | -0.000 [-0.000, -0.000] | +0.0002 [0.0001, 0.0003] | 100% |
| 365 d | survival model, SMART + context (reference) | 0.786 [0.776, 0.800] |  |  |  |
| 365 d | survival model, SMART without counters 5/187/188/197/198 | 0.707 [0.693, 0.724] | +0.079 [0.070, 0.087] | +0.1817 [0.1543, 0.2043] | 0% |
| 365 d | survival model, context + usage counters | 0.651 [0.638, 0.666] | +0.135 [0.124, 0.146] | +0.2676 [0.2429, 0.2923] | 0% |
| 365 d | survival model, SMART + context, weight power 0.75 | 0.785 [0.772, 0.797] | +0.001 [-0.004, 0.006] | +0.0334 [0.0141, 0.0481] | 38% |
| 365 d | survival model, SMART + context, weight power 1.0 | 0.783 [0.771, 0.796] | +0.003 [-0.003, 0.009] | +0.0314 [0.0114, 0.0531] | 15% |
| 365 d | survival model, SMART + context, recalibrated on the last year | 0.786 [0.776, 0.800] | -0.000 [-0.000, -0.000] | -0.0010 [-0.0015, -0.0005] | 100% |

## Where the signal comes from

The ranking metrics on parts of the test set, per drive-day snapshot. Positive-side slices (lead time, silent or not) keep every known-healthy snapshot and restrict the failing ones, so their base rate is lower; population slices (vendor, capacity, entry date) restrict both. "Silent" failures are drives that fail with none of the critical counters (5, 187, 197, 198) above zero in any test snapshot. At 30 days:

| slice | model | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| all test snapshots | survival model, SMART + context | 0.876 [0.866, 0.885] | 0.1239 [0.1061, 0.1473] | 0.121% | 1784 |
| all test snapshots | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.121% | 1784 |
| all test snapshots | rule: critical SMART counters (5, 187, 197, 198) | 0.823 [0.813, 0.833] | 0.0521 [0.0409, 0.0720] | 0.121% | 1784 |
| positives >= 7 days before failure | survival model, SMART + context | 0.868 [0.857, 0.877] | 0.0788 [0.0661, 0.0970] | 0.093% | 1755 |
| positives >= 7 days before failure | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0013 [0.0012, 0.0015] | 0.093% | 1755 |
| positives >= 7 days before failure | rule: critical SMART counters (5, 187, 197, 198) | 0.814 [0.804, 0.825] | 0.0333 [0.0259, 0.0485] | 0.093% | 1755 |
| silent failures (no critical counter above zero) | survival model, SMART + context | 0.639 [0.608, 0.666] | 0.0007 [0.0005, 0.0012] | 0.025% | 368 |
| silent failures (no critical counter above zero) | survival model, context only (no SMART) | 0.549 [0.516, 0.580] | 0.0003 [0.0003, 0.0003] | 0.025% | 368 |
| silent failures (no critical counter above zero) | rule: critical SMART counters (5, 187, 197, 198) | 0.473 [0.470, 0.475] | 0.0002 [0.0002, 0.0003] | 0.025% | 368 |
| failures with a critical counter above zero | survival model, SMART + context | 0.938 [0.931, 0.945] | 0.1498 [0.1271, 0.1775] | 0.096% | 1416 |
| failures with a critical counter above zero | survival model, context only (no SMART) | 0.618 [0.602, 0.634] | 0.0015 [0.0014, 0.0017] | 0.096% | 1416 |
| failures with a critical counter above zero | rule: critical SMART counters (5, 187, 197, 198) | 0.915 [0.907, 0.922] | 0.0653 [0.0519, 0.0892] | 0.096% | 1416 |
| vendor HGST | survival model, SMART + context | 0.923 [0.906, 0.940] | 0.0841 [0.0615, 0.1232] | 0.235% | 380 |
| vendor HGST | survival model, context only (no SMART) | 0.612 [0.583, 0.643] | 0.0033 [0.0029, 0.0040] | 0.235% | 380 |
| vendor HGST | rule: critical SMART counters (5, 187, 197, 198) | 0.888 [0.870, 0.908] | 0.0436 [0.0317, 0.0727] | 0.235% | 380 |
| vendor Seagate | survival model, SMART + context | 0.895 [0.880, 0.908] | 0.1770 [0.1478, 0.2130] | 0.139% | 764 |
| vendor Seagate | survival model, context only (no SMART) | 0.614 [0.592, 0.637] | 0.0022 [0.0020, 0.0026] | 0.139% | 764 |
| vendor Seagate | rule: critical SMART counters (5, 187, 197, 198) | 0.852 [0.837, 0.868] | 0.0881 [0.0659, 0.1332] | 0.139% | 764 |
| vendor Toshiba | survival model, SMART + context | 0.792 [0.763, 0.813] | 0.1179 [0.0982, 0.1473] | 0.104% | 485 |
| vendor Toshiba | survival model, context only (no SMART) | 0.513 [0.485, 0.535] | 0.0011 [0.0009, 0.0022] | 0.104% | 485 |
| vendor Toshiba | rule: critical SMART counters (5, 187, 197, 198) | 0.740 [0.716, 0.760] | 0.0674 [0.0516, 0.0973] | 0.104% | 485 |
| vendor WDC | survival model, SMART + context | 0.827 [0.788, 0.874] | 0.0619 [0.0355, 0.1064] | 0.054% | 155 |
| vendor WDC | survival model, context only (no SMART) | 0.543 [0.500, 0.586] | 0.0007 [0.0005, 0.0025] | 0.054% | 155 |
| vendor WDC | rule: critical SMART counters (5, 187, 197, 198) | 0.785 [0.751, 0.823] | 0.0427 [0.0280, 0.0775] | 0.054% | 155 |
| capacity >= 16 TB | survival model, SMART + context | 0.815 [0.791, 0.835] | 0.0740 [0.0544, 0.1021] | 0.075% | 530 |
| capacity >= 16 TB | survival model, context only (no SMART) | 0.585 [0.561, 0.615] | 0.0011 [0.0009, 0.0013] | 0.075% | 530 |
| capacity >= 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.754 [0.733, 0.773] | 0.0396 [0.0293, 0.0645] | 0.075% | 530 |
| capacity < 16 TB | survival model, SMART + context | 0.901 [0.890, 0.911] | 0.1459 [0.1219, 0.1779] | 0.165% | 1254 |
| capacity < 16 TB | survival model, context only (no SMART) | 0.531 [0.514, 0.546] | 0.0020 [0.0018, 0.0023] | 0.165% | 1254 |
| capacity < 16 TB | rule: critical SMART counters (5, 187, 197, 198) | 0.850 [0.838, 0.863] | 0.0591 [0.0453, 0.0873] | 0.165% | 1254 |
| in service before the panel starts | survival model, SMART + context | 0.903 [0.308, 0.984] | 0.1601 [0.0001, 0.8890] | 0.100% | 5 |
| in service before the panel starts | survival model, context only (no SMART) | 0.637 [0.293, 0.980] | 0.0142 [0.0001, 0.1640] | 0.100% | 5 |
| in service before the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.482 [0.447, 0.611] | 0.0010 [0.0001, 0.0024] | 0.100% | 5 |
| first seen after the panel starts | survival model, SMART + context | 0.876 [0.866, 0.885] | 0.1241 [0.1065, 0.1477] | 0.121% | 1779 |
| first seen after the panel starts | survival model, context only (no SMART) | 0.604 [0.591, 0.617] | 0.0017 [0.0016, 0.0019] | 0.121% | 1779 |
| first seen after the panel starts | rule: critical SMART counters (5, 187, 197, 198) | 0.824 [0.814, 0.833] | 0.0522 [0.0410, 0.0721] | 0.121% | 1779 |

The same two slices for survival model, SMART + context across horizons:

| slice | horizon | ROC-AUC | PR-AUC | base rate | positive drives |
|---|---|---|---|---|---|
| silent failures (no critical counter above zero) | 7 d | 0.658 [0.627, 0.686] | 0.0002 [0.0001, 0.0004] | 0.006% | 368 |
| silent failures (no critical counter above zero) | 30 d | 0.639 [0.608, 0.666] | 0.0007 [0.0005, 0.0012] | 0.025% | 368 |
| silent failures (no critical counter above zero) | 90 d | 0.616 [0.583, 0.643] | 0.0018 [0.0013, 0.0029] | 0.078% | 368 |
| silent failures (no critical counter above zero) | 180 d | 0.594 [0.566, 0.629] | 0.0034 [0.0026, 0.0052] | 0.172% | 368 |
| silent failures (no critical counter above zero) | 365 d | 0.572 [0.542, 0.606] | 0.0082 [0.0065, 0.0119] | 0.452% | 368 |
| positives >= 7 days before failure | 30 d | 0.868 [0.857, 0.877] | 0.0788 [0.0661, 0.0970] | 0.093% | 1755 |
| positives >= 7 days before failure | 90 d | 0.837 [0.826, 0.850] | 0.1516 [0.1311, 0.1792] | 0.357% | 1757 |
| positives >= 7 days before failure | 180 d | 0.811 [0.800, 0.822] | 0.1988 [0.1763, 0.2269] | 0.829% | 1758 |
| positives >= 7 days before failure | 365 d | 0.783 [0.772, 0.797] | 0.2983 [0.2741, 0.3253] | 2.215% | 1758 |

## Ranking over the whole future (concordance)

Concordance between each model's risk score and the actual time to failure; 0.5 = random. Harrell's C counts the comparable pairs (the earlier time is a failure) where the riskier snapshot fails first. Uno's C weights each pair by the inverse probability of staying uncensored, so it does not depend on how much follow-up the test period allows, and is truncated at 365 days. Computed on 299930 test snapshots of 3267 drives (drives sampled whole up to a row cap). Score: -rmst_days = minus the expected days survived within a year; p30 = predicted 30-day risk, so hazard models can be compared with the classifier on the same kind of score. Intervals only on each model's main score.

| model | score | Harrell's C | Uno's C |
|---|---|---|---|
| survival model, SMART + context | -rmst_days | 0.766 [0.745, 0.783] | 0.760 [0.740, 0.779] |
| survival model, SMART + context | p30 | 0.773 | 0.768 |
| survival model, context only (no SMART) | -rmst_days | 0.583 [0.559, 0.603] | 0.585 [0.559, 0.606] |
| survival model, context only (no SMART) | p30 | 0.597 | 0.599 |
| 30-day yes/no classifier (SMART + context) | p30 | 0.783 [0.768, 0.799] | 0.779 [0.763, 0.798] |
| rule: critical SMART counters (5, 187, 197, 198) | score | 0.717 [0.698, 0.730] | 0.709 [0.689, 0.723] |
| survival model, SMART without counters 5/187/188/197/198 | -rmst_days | 0.675 [0.651, 0.698] | 0.670 [0.646, 0.695] |
| survival model, SMART without counters 5/187/188/197/198 | p30 | 0.687 | 0.682 |
| survival model, context + usage counters | -rmst_days | 0.625 [0.602, 0.648] | 0.626 [0.603, 0.649] |
| survival model, context + usage counters | p30 | 0.632 | 0.633 |
| survival model, SMART + context, weight power 0.75 | -rmst_days | 0.765 [0.740, 0.783] | 0.758 [0.734, 0.778] |
| survival model, SMART + context, weight power 0.75 | p30 | 0.786 | 0.781 |
| survival model, SMART + context, weight power 1.0 | -rmst_days | 0.763 [0.742, 0.781] | 0.756 [0.735, 0.775] |
| survival model, SMART + context, weight power 1.0 | p30 | 0.785 | 0.780 |
| survival model, SMART + context, recalibrated on the last year | -rmst_days | 0.766 [0.746, 0.784] | 0.761 [0.740, 0.779] |
| survival model, SMART + context, recalibrated on the last year | p30 | 0.773 | 0.768 |

## When will it fail? Remaining-life estimates

From each snapshot the survival model gives a curve: the day by which the failure probability reaches 10%, 50% (the median remaining life) and 90%. Beyond 365 days the model has no bins, so the answer is "more than a year". For 0.6% of all test snapshots the predicted median of survival model, SMART + context is within a year; otherwise the answer is "more than a year".

**Are the predicted days right?** Among snapshots whose predicted day falls within a year, the share that actually failed by that day should be close to the target:

| model | failed by predicted 10% day | failed by predicted median | failed by predicted 90% day |
|---|---|---|---|
| survival model, SMART + context | 6.5% (target 10%, 113226 snapshots) | 33.0% (target 50%, 49398 snapshots) | 76.5% (target 90%, 12210 snapshots) |
| survival model, context only (no SMART) | 2.8% (target 10%, 7216 snapshots) | n/a (target 50%, 0 snapshots) | n/a (target 90%, 0 snapshots) |
| survival model, SMART without counters 5/187/188/197/198 | 6.7% (target 10%, 61537 snapshots) | 29.3% (target 50%, 10987 snapshots) | 22.6% (target 90%, 2018 snapshots) |
| survival model, context + usage counters | 3.5% (target 10%, 18024 snapshots) | 6.4% (target 50%, 99 snapshots) | n/a (target 90%, 0 snapshots) |
| survival model, SMART + context, weight power 0.75 | 6.7% (target 10%, 113604 snapshots) | 29.7% (target 50%, 50594 snapshots) | 45.3% (target 90%, 12010 snapshots) |
| survival model, SMART + context, weight power 1.0 | 6.8% (target 10%, 110707 snapshots) | 30.2% (target 50%, 48494 snapshots) | 51.8% (target 90%, 10317 snapshots) |
| survival model, SMART + context, recalibrated on the last year | 5.8% (target 10%, 116092 snapshots) | 30.6% (target 50%, 52254 snapshots) | 68.4% (target 90%, 14116 snapshots) |

**How early is a failure visible?** Snapshots of drives that do fail within a year, by how far away the failure actually was. A median within a year means the model already expects the drive to die within a year. The absolute error is over the failing snapshots whose median is within a year (count in brackets):

| model | failing snapshots: median within a year | abs. error of median (days) | all test snapshots: median within a year | healthy snapshots: median beyond a year |
|---|---|---|---|---|
| survival model, SMART + context | 16.9% | 103 (47578 snapshots) | 0.6% | 99.8% |
| survival model, context only (no SMART) | 0.0% | n/a (0 snapshots) | 0.0% | 100.0% |
| survival model, SMART without counters 5/187/188/197/198 | 3.6% | 132 (10539 snapshots) | 0.2% | 99.9% |
| survival model, context + usage counters | 0.0% | 169 (82 snapshots) | 0.0% | 100.0% |
| survival model, SMART + context, weight power 0.75 | 17.3% | 106 (48414 snapshots) | 0.6% | 99.7% |
| survival model, SMART + context, weight power 1.0 | 16.5% | 105 (46390 snapshots) | 0.6% | 99.7% |
| survival model, SMART + context, recalibrated on the last year | 18.0% | 98 (50222 snapshots) | 0.6% | 99.8% |

By actual time to failure (survival model, SMART + context). Shares are of the failing drives' snapshots in each bucket:

| actual days to failure | snapshots | median predicted within a year | median of predicted median (days) |
|---|---|---|---|
| 0-6 | 11632 | 48.4% | > 1 year |
| 7-13 | 11720 | 40.6% | > 1 year |
| 14-29 | 26982 | 34.5% | > 1 year |
| 30-59 | 48813 | 26.8% | > 1 year |
| 60-89 | 46454 | 21.4% | > 1 year |
| 90-179 | 18146 | 14.6% | > 1 year |
| 180-364 | 25961 | 8.5% | > 1 year |

![remaining life](remaining_life.png)

## Early warning

Each alert threshold is set on validation drives so that a given share of healthy drive-days raises an alert (the budget). At the main budget of 1.0%, 1.00% of validation drive-days alert for survival model, SMART + context; budgets of 0.1%, 0.3% are shown too. Test results: false alarms and precision are per drive-day; precision counts alerts whose outcome at 30 days is known, and the alerts that cannot be judged yet (panel end) are shown separately and, in the next column, counted as false. Failing drives alerted = drives failing in the test period that get at least one alert in their last 30 days.

| budget | model | false alarms, test (share of healthy drive-days) | precision (per alerted drive-day) | alerts with unknown outcome | precision, unknown as false | failing drives alerted (drives) | alerted >= 7 days before failure (drives) |
|---|---|---|---|---|---|---|---|
| 0.1% | survival model, SMART + context | 0.22% [0.17%, 0.27%] | 14.55% [12.24%, 17.56%] | 9.4% | 13.19% [11.05%, 16.03%] | 1021/1784, 57% [55%, 59%] | 782/1784 |
| 0.1% | survival model, context only (no SMART) | 0.03% [0.02%, 0.05%] | 0.69% [0.00%, 1.78%] | 0.0% | 0.69% [0.00%, 1.78%] | 3/1784, 0% [0%, 0%] | 3/1784 |
| 0.1% | 30-day yes/no classifier (SMART + context) | 0.35% [0.28%, 0.41%] | 10.96% [9.42%, 13.36%] | 8.3% | 10.05% [8.60%, 12.16%] | 1115/1784, 62% [60%, 65%] | 846/1784 |
| 0.1% | rule: critical SMART counters (5, 187, 197, 198) | 0.48% [0.35%, 0.58%] | 5.89% [4.83%, 7.84%] | 6.6% | 5.50% [4.53%, 7.30%] | 664/1784, 37% [35%, 39%] | 500/1784 |
| 0.1% | survival model, SMART + context, recalibrated on the last year | 0.22% [0.17%, 0.27%] | 14.59% [12.28%, 17.65%] | 9.4% | 13.22% [11.09%, 16.08%] | 1021/1784, 57% [55%, 59%] | 783/1784 |
| 0.3% | survival model, SMART + context | 0.61% [0.51%, 0.70%] | 8.31% [7.26%, 9.88%] | 7.9% | 7.65% [6.69%, 9.10%] | 1264/1784, 71% [69%, 73%] | 1028/1784 |
| 0.3% | survival model, context only (no SMART) | 0.36% [0.30%, 0.44%] | 0.29% [0.13%, 0.46%] | 2.2% | 0.28% [0.13%, 0.45%] | 17/1784, 1% [1%, 1%] | 15/1784 |
| 0.3% | 30-day yes/no classifier (SMART + context) | 0.81% [0.69%, 0.93%] | 6.97% [6.08%, 8.20%] | 7.5% | 6.45% [5.60%, 7.58%] | 1308/1784, 73% [71%, 75%] | 1086/1784 |
| 0.3% | rule: critical SMART counters (5, 187, 197, 198) | 0.79% [0.62%, 0.92%] | 4.84% [4.08%, 6.16%] | 6.9% | 4.51% [3.82%, 5.75%] | 839/1784, 47% [45%, 49%] | 664/1784 |
| 0.3% | survival model, SMART + context, recalibrated on the last year | 0.61% [0.51%, 0.70%] | 8.32% [7.28%, 9.89%] | 8.0% | 7.66% [6.71%, 9.11%] | 1265/1784, 71% [69%, 73%] | 1028/1784 |
| 1.0% | survival model, SMART + context | 1.55% [1.35%, 1.70%] | 4.38% [3.94%, 5.05%] | 6.8% | 4.09% [3.67%, 4.72%] | 1372/1784, 77% [75%, 79%] | 1181/1784 |
| 1.0% | survival model, context only (no SMART) | 1.11% [0.96%, 1.31%] | 0.27% [0.19%, 0.36%] | 12.4% | 0.23% [0.17%, 0.31%] | 47/1784, 3% [2%, 3%] | 46/1784 |
| 1.0% | 30-day yes/no classifier (SMART + context) | 1.88% [1.67%, 2.07%] | 3.77% [3.41%, 4.29%] | 6.8% | 3.51% [3.17%, 4.02%] | 1412/1784, 79% [77%, 81%] | 1216/1784 |
| 1.0% | rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 6.0% | 2.88% [2.51%, 3.43%] | 1051/1784, 59% [57%, 61%] | 874/1784 |
| 1.0% | survival model, SMART + context, recalibrated on the last year | 1.54% [1.35%, 1.70%] | 4.39% [3.95%, 5.06%] | 6.8% | 4.09% [3.67%, 4.73%] | 1372/1784, 77% [75%, 79%] | 1181/1784 |

At the main budget the test false-alarm rate is above the budget, with an interval that excludes it, for survival model, SMART + context, 30-day yes/no classifier (SMART + context), rule: critical SMART counters (5, 187, 197, 198), survival model, SMART + context, recalibrated on the last year: healthy test drives score higher than the validation drives the threshold was set on. This is the same shift over time that Calibration over time shows (drift).

![detection](detection.png)

## Calibration

Mean predicted failure probability vs the Kaplan-Meier observed share, by decile of predicted risk. Points on the diagonal mean that a predicted 5% really fails 5% of the time.

![calibration](calibration.png)

**Calibration over time** (mean predicted vs observed risk of failing within 30 days; ratio = predicted / observed with a 95% drive bootstrap). Validation drives are from the training era, test from 2024 on. A gap that appears only in the test years is drift. "Outside band" = the test year's ratio is outside the range of the validation-year ratios. Reference = survival model, SMART + context; recalibrated = survival model, SMART + context, recalibrated on the last year.

| split | year | snapshots | observed | predicted (reference) | ratio (reference) | outside band (reference) | predicted (recalibrated) | ratio (recalibrated) | outside band (recalibrated) |
|---|---|---|---|---|---|---|---|---|---|
| val | 2016 | 70518 | 0.162% | 0.154% | 0.95 [0.80, 1.12] | - | 0.175% | 1.08 [0.91, 1.27] | - |
| val | 2017 | 85198 | 0.154% | 0.154% | 0.99 [0.80, 1.21] | - | 0.173% | 1.12 [0.90, 1.36] | - |
| val | 2018 | 102268 | 0.134% | 0.119% | 0.89 [0.74, 1.06] | - | 0.136% | 1.01 [0.85, 1.20] | - |
| val | 2019 | 116101 | 0.165% | 0.156% | 0.94 [0.76, 1.20] | - | 0.176% | 1.07 [0.86, 1.36] | - |
| val | 2020 | 137012 | 0.084% | 0.120% | 1.44 [1.16, 1.78] | - | 0.137% | 1.63 [1.32, 2.01] | - |
| val | 2021 | 169154 | 0.088% | 0.103% | 1.17 [1.00, 1.36] | - | 0.117% | 1.33 [1.14, 1.54] | - |
| val | 2022 | 191823 | 0.109% | 0.136% | 1.25 [1.09, 1.43] | - | 0.153% | 1.41 [1.23, 1.61] | - |
| val | 2023 | 205355 | 0.166% | 0.153% | 0.92 [0.83, 1.03] | - | 0.172% | 1.03 [0.93, 1.16] | - |
| test | 2024 | 422201 | 0.133% | 0.161% | 1.21 [1.11, 1.30] | no | 0.181% | 1.36 [1.25, 1.46] | no |
| test | 2025 | 403120 | 0.103% | 0.236% | 2.28 [1.97, 2.67] | yes | 0.264% | 2.55 [2.21, 2.97] | yes |

- survival model, SMART + context: predicted/observed ratio over validation years spans 0.89 to 1.44. The last validation year (2023, ratio 0.92) is inside the band of the earlier validation years. Test years outside the band: 2025.
- survival model, SMART + context, recalibrated on the last year: predicted/observed ratio over validation years spans 1.01 to 1.63. The last validation year (2023, ratio 1.03) is inside the band of the earlier validation years. Test years outside the band: 2025.

## Retirement

Drives that never fail and have snapshots in a year, split into those that stop reporting before the end of the next year (left) and those still reporting (stayed). The survival estimates assume that leaving is unrelated to health; then both groups would carry about the same predicted risk. A ratio above 1 means the drives that leave already looked riskier beforehand: censoring is probably informative (drives are retired before they can fail), and the observed failure risk is underestimated. The alert threshold is the main-budget threshold of survival model, SMART + context.

| split | year | drives left | drives stayed | mean predicted 30-day risk, left | mean predicted 30-day risk, stayed | ratio left/stayed | above alert threshold, left | above alert threshold, stayed |
|---|---|---|---|---|---|---|---|---|
| val | 2016 | 170 | 538 | 0.232% | 0.036% | 6.48 | 1.91% | 0.17% |
| val | 2017 | 280 | 672 | 0.206% | 0.041% | 5.08 | 2.51% | 0.33% |
| val | 2018 | 236 | 869 | 0.157% | 0.070% | 2.24 | 1.26% | 0.42% |
| val | 2019 | 233 | 964 | 0.137% | 0.113% | 1.21 | 0.30% | 0.81% |
| val | 2020 | 357 | 1270 | 0.134% | 0.064% | 2.10 | 0.81% | 0.42% |
| val | 2021 | 202 | 1828 | 0.116% | 0.058% | 2.00 | 0.86% | 0.28% |
| val | 2022 | 101 | 2040 | 0.160% | 0.070% | 2.29 | 3.49% | 0.44% |
| val | 2023 | 282 | 2383 | 0.191% | 0.078% | 2.45 | 2.72% | 0.55% |
| test | 2024 | 509 | 5809 | 0.226% | 0.100% | 2.25 | 2.05% | 0.88% |

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

![importance](importance.png)

Also see `build/explore/km_by_counters.png` and `build/explore/models.csv`.

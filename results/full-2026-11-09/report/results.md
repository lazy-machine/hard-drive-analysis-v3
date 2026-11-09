# Results

Numbers only. What they mean, and the detailed tables behind them, are in [analysis.md](analysis.md).

## Run

|  |  |
|---|---|
| scale | full (failing drives sampled at 100%, healthy at 10.0%) |
| cohort | 57309 drives (train 42330, val 5997, test 8982) |
| validation snapshots | 2016-01-01 to 2023-12-31 |
| test snapshots | 2024-01-01 to 2025-12-31 |
| test set | 8981 drives, 1784 fail (368 silent), 825321 snapshots |
| reference model | survival model, SMART + context |
| compared with | 8 models and baselines (rows of the tables below) |
| verification gate | 55/56 checks passed (data-verify 0.4.0; 14 skipped: their roles are not declared); assert.cohort_drives_have_snapshots warned |
| intervals | 95% drive-level bootstrap, 200 rounds |

## Ranking (ROC-AUC)

> How well the score separates drives that fail within the horizon from those that don't. 0.5 = random, 1 = perfect.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, SMART + context | 0.907 [0.897, 0.916] | 0.879 [0.869, 0.887] | 0.846 [0.836, 0.858] | 0.818 [0.807, 0.829] | 0.789 [0.778, 0.802] |
| survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.604 [0.591, 0.617] | 0.601 [0.586, 0.616] | 0.593 [0.580, 0.605] | 0.574 [0.560, 0.591] |
| 30-day yes/no classifier (SMART + context) | - | 0.879 [0.868, 0.886] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.823 [0.813, 0.833] | 0.786 [0.776, 0.798] | 0.755 [0.744, 0.764] | 0.722 [0.711, 0.732] |

## Precision-recall (PR-AUC)

> Failures are rare, so compare each value with the base rate (the real share of drive-days that fail within the horizon), which is what a random ranking scores.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| base rate | 0.00027 | 0.00121 | 0.00388 | 0.00865 | 0.02272 |
| survival model, SMART + context | 0.0729 [0.0615, 0.0859] | 0.1301 [0.1102, 0.1515] | 0.1853 [0.1625, 0.2128] | 0.2201 [0.1961, 0.2497] | 0.3128 [0.2885, 0.3393] |
| survival model, context only (no SMART) | 0.0004 [0.0004, 0.0004] | 0.0017 [0.0016, 0.0019] | 0.0054 [0.0050, 0.0058] | 0.0117 [0.0110, 0.0125] | 0.0305 [0.0280, 0.0340] |
| 30-day yes/no classifier (SMART + context) | - | 0.1156 [0.0975, 0.1353] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.0295 [0.0225, 0.0400] | 0.0521 [0.0409, 0.0720] | 0.0893 [0.0733, 0.1164] | 0.1295 [0.1095, 0.1524] | 0.2145 [0.1873, 0.2420] |

## Reference gain over each model (ROC-AUC)

> The reference (survival model, SMART + context) minus the model in the row, paired on the same bootstrap rounds. An interval above zero means the reference ranks better; one that covers zero means no clear difference.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, context only (no SMART) | +0.301 [0.283, 0.315] | +0.275 [0.263, 0.290] | +0.245 [0.229, 0.262] | +0.224 [0.212, 0.238] | +0.214 [0.198, 0.231] |
| 30-day yes/no classifier (SMART + context) | - | -0.000 [-0.003, 0.003] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | +0.055 [0.047, 0.062] | +0.055 [0.048, 0.063] | +0.060 [0.052, 0.069] | +0.063 [0.055, 0.072] | +0.067 [0.057, 0.077] |
| survival model, SMART without counters 5/187/188/197/198 | +0.101 [0.091, 0.109] | +0.101 [0.093, 0.110] | +0.094 [0.087, 0.105] | +0.092 [0.082, 0.101] | +0.082 [0.073, 0.091] |
| survival model, context + usage counters | +0.253 [0.239, 0.266] | +0.225 [0.213, 0.238] | +0.192 [0.181, 0.207] | +0.165 [0.154, 0.179] | +0.138 [0.127, 0.149] |
| survival model, SMART + context, weight power 0.75 | +0.003 [0.000, 0.006] | +0.001 [-0.002, 0.003] | +0.004 [0.000, 0.007] | +0.007 [0.003, 0.012] | +0.007 [0.003, 0.013] |
| survival model, SMART + context, weight power 1.0 | +0.004 [0.001, 0.007] | +0.002 [-0.001, 0.005] | +0.001 [-0.003, 0.005] | +0.008 [0.003, 0.013] | +0.006 [0.001, 0.011] |
| survival model, SMART + context, recalibrated on the last year | 0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | +0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | -0.000 [-0.001, -0.000] |

## Alerts at a 1.0% false-alarm budget

> The threshold is set on validation drives so that 1.0% of healthy drive-days alert. On test, false alarms above the budget mean drift. Precision = share of alerted drive-days that fail within 30 days.

| model | false alarms (test) | precision | failing drives alerted in their last 30 d | alerted >= 7 d before failure |
|---|---|---|---|---|
| survival model, SMART + context | 1.57% [1.38%, 1.76%] | 4.37% [3.95%, 5.03%] | 1375/1784 | 1184/1784 |
| survival model, context only (no SMART) | 1.11% [0.96%, 1.31%] | 0.27% [0.19%, 0.36%] | 47/1784 | 46/1784 |
| 30-day yes/no classifier (SMART + context) | 1.98% [1.75%, 2.19%] | 3.62% [3.30%, 4.13%] | 1412/1784 | 1215/1784 |
| rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 1051/1784 | 874/1784 |

## Remaining life

> For each snapshot the model names the day by which the failure probability reaches 10%, 50% and 90%. If the timing is right, the share that failed by that day matches the target. Below target = too pessimistic, above = too optimistic.

| predicted day | target | failed by then | snapshots |
|---|---|---|---|
| 10% day | 10% | 6.6% | 115829 |
| median | 50% | 37.2% | 48520 |
| 90% day | 90% | 81.9% | 9897 |

Failing drives' snapshots with a median within a year: 16.6%. Healthy snapshots with a median beyond a year: 99.8%.

## Calibration over time (30-day risk)

> Ratio = mean predicted / observed risk. 1 = right, above 1 = the model over-predicts. Validation years span 0.85 to 1.44; a test year outside that band is drift.

| test year | ratio | outside validation band |
|---|---|---|
| 2024 | 1.21 [1.11, 1.33] | no |
| 2025 | 2.15 [1.87, 2.49] | yes |

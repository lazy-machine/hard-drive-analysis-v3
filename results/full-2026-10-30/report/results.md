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
| verification gate | 52/54 checks passed (data-verify 0.1.0; 12 skipped: their roles are not declared); features.constant warned; assert.cohort_drives_have_snapshots warned |
| intervals | 95% drive-level bootstrap, 200 rounds |

## Ranking (ROC-AUC)

> How well the score separates drives that fail within the horizon from those that don't. 0.5 = random, 1 = perfect.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, SMART + context | 0.906 [0.896, 0.915] | 0.876 [0.866, 0.885] | 0.843 [0.832, 0.855] | 0.814 [0.804, 0.826] | 0.786 [0.776, 0.800] |
| survival model, context only (no SMART) | 0.606 [0.591, 0.619] | 0.604 [0.591, 0.617] | 0.601 [0.586, 0.616] | 0.593 [0.580, 0.605] | 0.574 [0.560, 0.591] |
| 30-day yes/no classifier (SMART + context) | - | 0.877 [0.867, 0.885] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.823 [0.813, 0.833] | 0.786 [0.776, 0.798] | 0.755 [0.744, 0.764] | 0.722 [0.711, 0.732] |

## Precision-recall (PR-AUC)

> Failures are rare, so compare each value with the base rate (the real share of drive-days that fail within the horizon), which is what a random ranking scores.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| base rate | 0.00027 | 0.00121 | 0.00388 | 0.00865 | 0.02272 |
| survival model, SMART + context | 0.0674 [0.0574, 0.0809] | 0.1239 [0.1061, 0.1473] | 0.1798 [0.1568, 0.2099] | 0.2191 [0.1956, 0.2478] | 0.3123 [0.2885, 0.3386] |
| survival model, context only (no SMART) | 0.0004 [0.0004, 0.0004] | 0.0017 [0.0016, 0.0019] | 0.0054 [0.0050, 0.0058] | 0.0117 [0.0110, 0.0125] | 0.0305 [0.0280, 0.0340] |
| 30-day yes/no classifier (SMART + context) | - | 0.1170 [0.1000, 0.1372] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.0295 [0.0225, 0.0400] | 0.0521 [0.0409, 0.0720] | 0.0893 [0.0733, 0.1164] | 0.1295 [0.1095, 0.1524] | 0.2145 [0.1873, 0.2420] |

## Reference gain over each model (ROC-AUC)

> The reference (survival model, SMART + context) minus the model in the row, paired on the same bootstrap rounds. An interval above zero means the reference ranks better; one that covers zero means no clear difference.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, context only (no SMART) | +0.300 [0.282, 0.314] | +0.273 [0.260, 0.288] | +0.241 [0.225, 0.259] | +0.221 [0.208, 0.236] | +0.211 [0.197, 0.228] |
| 30-day yes/no classifier (SMART + context) | - | -0.001 [-0.004, 0.002] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | +0.053 [0.046, 0.061] | +0.053 [0.045, 0.060] | +0.057 [0.048, 0.065] | +0.060 [0.051, 0.068] | +0.064 [0.055, 0.074] |
| survival model, SMART without counters 5/187/188/197/198 | +0.105 [0.096, 0.113] | +0.104 [0.096, 0.112] | +0.096 [0.087, 0.106] | +0.093 [0.084, 0.101] | +0.079 [0.070, 0.087] |
| survival model, context + usage counters | +0.251 [0.236, 0.264] | +0.222 [0.211, 0.236] | +0.188 [0.177, 0.204] | +0.161 [0.151, 0.175] | +0.135 [0.124, 0.146] |
| survival model, SMART + context, weight power 0.75 | +0.001 [-0.003, 0.004] | -0.003 [-0.007, 0.000] | -0.003 [-0.007, 0.001] | +0.002 [-0.003, 0.006] | +0.001 [-0.004, 0.006] |
| survival model, SMART + context, weight power 1.0 | +0.002 [-0.002, 0.006] | -0.002 [-0.006, 0.000] | -0.006 [-0.009, -0.002] | +0.002 [-0.002, 0.008] | +0.003 [-0.003, 0.009] |
| survival model, SMART + context, recalibrated on the last year | 0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | +0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | -0.000 [-0.000, -0.000] |

## Alerts at a 1.0% false-alarm budget

> The threshold is set on validation drives so that 1.0% of healthy drive-days alert. On test, false alarms above the budget mean drift. Precision = share of alerted drive-days that fail within 30 days.

| model | false alarms (test) | precision | failing drives alerted in their last 30 d | alerted >= 7 d before failure |
|---|---|---|---|---|
| survival model, SMART + context | 1.55% [1.35%, 1.70%] | 4.38% [3.94%, 5.05%] | 1372/1784 | 1181/1784 |
| survival model, context only (no SMART) | 1.11% [0.96%, 1.31%] | 0.27% [0.19%, 0.36%] | 47/1784 | 46/1784 |
| 30-day yes/no classifier (SMART + context) | 1.88% [1.67%, 2.07%] | 3.77% [3.41%, 4.29%] | 1412/1784 | 1216/1784 |
| rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 1051/1784 | 874/1784 |

## Remaining life

> For each snapshot the model names the day by which the failure probability reaches 10%, 50% and 90%. If the timing is right, the share that failed by that day matches the target. Below target = too pessimistic, above = too optimistic.

| predicted day | target | failed by then | snapshots |
|---|---|---|---|
| 10% day | 10% | 6.5% | 113226 |
| median | 50% | 33.0% | 49398 |
| 90% day | 90% | 76.5% | 12210 |

Failing drives' snapshots with a median within a year: 16.9%. Healthy snapshots with a median beyond a year: 99.8%.

## Calibration over time (30-day risk)

> Ratio = mean predicted / observed risk. 1 = right, above 1 = the model over-predicts. Validation years span 0.89 to 1.44; a test year outside that band is drift.

| test year | ratio | outside validation band |
|---|---|---|
| 2024 | 1.21 [1.11, 1.30] | no |
| 2025 | 2.28 [1.97, 2.67] | yes |

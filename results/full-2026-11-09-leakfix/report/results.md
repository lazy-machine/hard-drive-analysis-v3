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
| survival model, SMART + context | 0.904 [0.893, 0.913] | 0.875 [0.863, 0.883] | 0.840 [0.829, 0.851] | 0.810 [0.798, 0.821] | 0.785 [0.774, 0.798] |
| survival model, context only (no SMART) | 0.606 [0.592, 0.620] | 0.604 [0.590, 0.617] | 0.606 [0.591, 0.621] | 0.600 [0.586, 0.612] | 0.578 [0.563, 0.595] |
| 30-day yes/no classifier (SMART + context) | - | 0.880 [0.870, 0.888] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.823 [0.813, 0.833] | 0.786 [0.776, 0.798] | 0.755 [0.744, 0.764] | 0.722 [0.711, 0.732] |

## Precision-recall (PR-AUC)

> Failures are rare, so compare each value with the base rate (the real share of drive-days that fail within the horizon), which is what a random ranking scores.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| base rate | 0.00027 | 0.00121 | 0.00388 | 0.00865 | 0.02272 |
| survival model, SMART + context | 0.0648 [0.0541, 0.0784] | 0.1237 [0.1059, 0.1475] | 0.1769 [0.1532, 0.2040] | 0.2166 [0.1940, 0.2478] | 0.3130 [0.2894, 0.3402] |
| survival model, context only (no SMART) | 0.0004 [0.0004, 0.0005] | 0.0018 [0.0017, 0.0020] | 0.0058 [0.0053, 0.0063] | 0.0128 [0.0119, 0.0139] | 0.0340 [0.0307, 0.0389] |
| 30-day yes/no classifier (SMART + context) | - | 0.1272 [0.1100, 0.1464] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.0295 [0.0225, 0.0400] | 0.0521 [0.0409, 0.0720] | 0.0893 [0.0733, 0.1164] | 0.1295 [0.1095, 0.1524] | 0.2145 [0.1873, 0.2420] |

## Reference gain over each model (ROC-AUC)

> The reference (survival model, SMART + context) minus the model in the row, paired on the same bootstrap rounds. An interval above zero means the reference ranks better; one that covers zero means no clear difference.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, context only (no SMART) | +0.297 [0.280, 0.310] | +0.271 [0.257, 0.287] | +0.234 [0.218, 0.252] | +0.210 [0.195, 0.224] | +0.208 [0.189, 0.224] |
| 30-day yes/no classifier (SMART + context) | - | -0.006 [-0.009, -0.002] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | +0.051 [0.043, 0.059] | +0.051 [0.043, 0.058] | +0.054 [0.045, 0.062] | +0.055 [0.046, 0.063] | +0.063 [0.054, 0.074] |
| survival model, SMART without counters 5/187/188/197/198 | +0.100 [0.091, 0.110] | +0.101 [0.092, 0.109] | +0.095 [0.087, 0.106] | +0.095 [0.085, 0.104] | +0.078 [0.069, 0.086] |
| survival model, context + usage counters | +0.248 [0.232, 0.260] | +0.219 [0.209, 0.233] | +0.184 [0.172, 0.201] | +0.154 [0.141, 0.167] | +0.124 [0.111, 0.137] |
| survival model, SMART + context, weight power 0.75 | -0.004 [-0.007, -0.000] | -0.006 [-0.009, -0.003] | -0.007 [-0.011, -0.004] | -0.004 [-0.008, -0.001] | -0.003 [-0.007, 0.001] |
| survival model, SMART + context, weight power 1.0 | +0.001 [-0.003, 0.005] | -0.002 [-0.006, 0.001] | -0.004 [-0.008, 0.000] | -0.002 [-0.005, 0.002] | -0.001 [-0.006, 0.004] |
| survival model, SMART + context, recalibrated on the last year | 0.000 [0.000, 0.000] | +0.000 [-0.000, 0.000] | +0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | -0.000 [-0.000, -0.000] |

## Alerts at a 1.0% false-alarm budget

> The threshold is set on validation drives so that 1.0% of healthy drive-days alert. On test, false alarms above the budget mean drift. Precision = share of alerted drive-days that fail within 30 days.

| model | false alarms (test) | precision | failing drives alerted in their last 30 d | alerted >= 7 d before failure |
|---|---|---|---|---|
| survival model, SMART + context | 1.95% [1.71%, 2.15%] | 3.66% [3.32%, 4.18%] | 1396/1784 | 1209/1784 |
| survival model, context only (no SMART) | 1.89% [1.68%, 2.16%] | 0.36% [0.28%, 0.46%] | 116/1784 | 110/1784 |
| 30-day yes/no classifier (SMART + context) | 2.00% [1.78%, 2.22%] | 3.63% [3.29%, 4.08%] | 1421/1784 | 1226/1784 |
| rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 1051/1784 | 874/1784 |

## Remaining life

> For each snapshot the model names the day by which the failure probability reaches 10%, 50% and 90%. If the timing is right, the share that failed by that day matches the target. Below target = too pessimistic, above = too optimistic. "Known outcomes" drops snapshots censored before their day, which favours early days; "IPCW" reweights them instead. Both assume retirement is unrelated to failure.

| predicted day | target | failed by then (IPCW) | failed by then (known outcomes) | snapshots |
|---|---|---|---|---|
| 10% day | 10% | 5.9% | 6.9% | 113992 |
| median | 50% | 30.6% | 35.2% | 47669 |
| 90% day | 90% | 75.5% | 79.2% | 9858 |

Failing drives' snapshots with a median within a year: 15.9%. Healthy snapshots with a median beyond a year: 99.8%.

## Calibration over time (30-day risk)

> Ratio = mean predicted / observed risk. 1 = right, above 1 = the model over-predicts. Validation years span 0.86 to 1.35; a test year outside that band is drift.

| test year | ratio | outside validation band |
|---|---|---|
| 2024 | 1.17 [1.09, 1.28] | no |
| 2025 | 2.28 [1.98, 2.65] | yes |

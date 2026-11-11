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
| verification gate | 55/56 checks passed (data-verify 0.4.1; 14 skipped as not applicable; reasons in verify-report.md); assert.cohort_drives_have_snapshots warned |
| intervals | 95% drive-level bootstrap, 200 rounds |

## Ranking (ROC-AUC)

> How well the score separates drives that fail within the horizon from those that don't. 0.5 = random, 1 = perfect.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, SMART + context | 0.905 [0.895, 0.914] | 0.877 [0.865, 0.886] | 0.843 [0.832, 0.855] | 0.813 [0.801, 0.825] | 0.787 [0.777, 0.801] |
| survival model, context only (no SMART) | 0.603 [0.590, 0.617] | 0.603 [0.589, 0.616] | 0.609 [0.595, 0.623] | 0.606 [0.594, 0.619] | 0.585 [0.570, 0.602] |
| 30-day yes/no classifier (SMART + context) | - | 0.878 [0.868, 0.885] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.853 [0.842, 0.864] | 0.823 [0.813, 0.833] | 0.786 [0.776, 0.798] | 0.755 [0.744, 0.764] | 0.722 [0.711, 0.732] |

## Precision-recall (PR-AUC)

> Failures are rare, so compare each value with the base rate (the real share of drive-days that fail within the horizon), which is what a random ranking scores.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| base rate | 0.00027 | 0.00121 | 0.00388 | 0.00865 | 0.02272 |
| survival model, SMART + context | 0.0650 [0.0534, 0.0816] | 0.1235 [0.1053, 0.1466] | 0.1821 [0.1582, 0.2103] | 0.2194 [0.1957, 0.2474] | 0.3117 [0.2888, 0.3389] |
| survival model, context only (no SMART) | 0.0004 [0.0004, 0.0005] | 0.0019 [0.0017, 0.0021] | 0.0059 [0.0054, 0.0065] | 0.0131 [0.0122, 0.0142] | 0.0339 [0.0307, 0.0385] |
| 30-day yes/no classifier (SMART + context) | - | 0.1182 [0.1006, 0.1373] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | 0.0295 [0.0225, 0.0400] | 0.0521 [0.0409, 0.0720] | 0.0893 [0.0733, 0.1164] | 0.1295 [0.1095, 0.1524] | 0.2145 [0.1873, 0.2420] |

## Reference gain over each model (ROC-AUC)

> The reference (survival model, SMART + context) minus the model in the row, paired on the same bootstrap rounds. An interval above zero means the reference ranks better; one that covers zero means no clear difference.

| model | 7 d | 30 d | 90 d | 180 d | 365 d |
|---|---|---|---|---|---|
| survival model, context only (no SMART) | +0.302 [0.284, 0.316] | +0.273 [0.260, 0.291] | +0.234 [0.219, 0.253] | +0.207 [0.194, 0.221] | +0.203 [0.188, 0.219] |
| 30-day yes/no classifier (SMART + context) | - | -0.001 [-0.004, 0.002] | - | - | - |
| rule: critical SMART counters (5, 187, 197, 198) | +0.052 [0.045, 0.060] | +0.053 [0.045, 0.060] | +0.057 [0.049, 0.066] | +0.058 [0.050, 0.067] | +0.066 [0.057, 0.077] |
| survival model, SMART without counters 5/187/188/197/198 | +0.106 [0.096, 0.115] | +0.106 [0.098, 0.114] | +0.098 [0.090, 0.110] | +0.093 [0.084, 0.102] | +0.075 [0.067, 0.084] |
| survival model, context + usage counters | +0.250 [0.235, 0.262] | +0.222 [0.211, 0.236] | +0.187 [0.175, 0.203] | +0.155 [0.143, 0.167] | +0.123 [0.110, 0.135] |
| survival model, SMART + context, weight power 0.75 | -0.002 [-0.004, 0.000] | -0.003 [-0.006, -0.000] | -0.003 [-0.006, 0.000] | -0.000 [-0.004, 0.003] | +0.000 [-0.003, 0.004] |
| survival model, SMART + context, weight power 1.0 | +0.001 [-0.002, 0.005] | -0.000 [-0.003, 0.003] | -0.002 [-0.005, 0.002] | +0.001 [-0.003, 0.005] | -0.000 [-0.004, 0.004] |
| survival model, SMART + context, recalibrated on the last year | 0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | +0.000 [0.000, 0.000] | -0.000 [-0.000, -0.000] | -0.000 [-0.000, -0.000] |

## Alerts at a 1.0% false-alarm budget

> The threshold is set on validation drives so that 1.0% of healthy drive-days alert. On test, false alarms above the budget mean drift. Precision = share of alerted drive-days that fail within 30 days.

| model | false alarms (test) | precision | failing drives alerted in their last 30 d | alerted >= 7 d before failure |
|---|---|---|---|---|
| survival model, SMART + context | 1.87% [1.64%, 2.07%] | 3.82% [3.45%, 4.40%] | 1391/1784 | 1203/1784 |
| survival model, context only (no SMART) | 2.55% [2.31%, 2.87%] | 0.33% [0.27%, 0.40%] | 141/1784 | 135/1784 |
| 30-day yes/no classifier (SMART + context) | 2.22% [1.99%, 2.44%] | 3.30% [3.02%, 3.70%] | 1426/1784 | 1231/1784 |
| rule: critical SMART counters (5, 187, 197, 198) | 1.74% [1.48%, 2.01%] | 3.06% [2.67%, 3.65%] | 1051/1784 | 874/1784 |

## Remaining life

> For each snapshot the model names the day by which the failure probability reaches 10%, 50% and 90%. If the timing is right, the weighted share of snapshots that failed by that day matches the target. Below target = too pessimistic, above = too optimistic. "Known outcomes" drops snapshots censored before their outcome is known, which favours early days; "IPCW" reweights the known ones instead, assuming censoring is unrelated to both the failure time and the predicted day. Neither corrects for retirement related to health.

| predicted day | target | failed by then (IPCW) | failed by then (known outcomes) | snapshots |
|---|---|---|---|---|
| 10% day | 10% | 6.0% | 7.0% | 113802 |
| median | 50% | 33.7% | 38.3% | 45249 |
| 90% day | 90% | 79.8% | 82.5% | 7981 |

Failing drives' snapshots with a median within a year: 15.0%. Healthy snapshots with a median beyond a year: 99.9%.

## Calibration over time (30-day risk)

> Ratio = mean predicted / observed risk. 1 = right, above 1 = the model over-predicts. Validation years span 0.86 to 1.38; a test year outside that band is drift.

| test year | ratio | outside validation band |
|---|---|---|
| 2024 | 1.18 [1.09, 1.28] | no |
| 2025 | 2.18 [1.89, 2.51] | yes |

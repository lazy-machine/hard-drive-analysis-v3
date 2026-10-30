# Researcher review: code, evaluation and the Backblaze dataset

- **Date:** 2026-10-25
- **Commit:** `398f421` (working tree clean apart from untracked docs)
- **Reviewer:** Claude Opus 5.5, after the literature review in
  `reports/SMART failure prediction methodology debate.md` (sources in `article/research/`)
- **Scope:** `steps/`, `tests/`, `config/`, `pipeline.toml`, `pyproject.toml`, and the
  full-scale outputs in `build-arch/`. The orchestrator in `../data-pipeline` was not read.
- **Method:** I read every step module and test, then checked suspected problems against
  `build-arch/` (the full run: 57,309 drives, 1,784 failing test drives) and
  `dataset/dataset.parquet`. The checks were one-off DuckDB and numpy queries that call the
  project's own `metrics`, `survival` and `predict` functions. No project file was changed.

This review avoids repeating `audit/flint-review.md` and `audit/gwen-3-8-review.md`.
Section 5 lists the points they already cover.

## 1. Verdict

The statistical core is sound and better built than most published disk-failure work.
The survival labels, the drive-and-time split, the inverse-probability weights and the
weighted metrics are correct, and each is tested against an independent computation. I
found no bug that changes a headline ROC-AUC.

I did find four problems that change how the results should be read:

| # | Finding | Severity | Effect |
|---|---|---|---|
| R1 | The feature-importance figure plots the first 20 features in alphabetical order, not the top 20 by gain | High | The report's figure is wrong |
| R2 | Seagate's vendor-packed SMART 188 raw values take up 89% of the counter rule's false-alarm budget | High | The early-warning lead over the rule is overstated: 77% vs 37% of failing drives becomes 77% vs 60% |
| R3 | No ablation or test slice addresses label circularity | High | On failures with no critical-counter warning, 30-day ROC-AUC is 0.627, against 0.875 overall |
| R4 | Snapshots taken in the last days before failure carry the precision metrics | Medium | 30-day PR-AUC drops from 0.127 to 0.080 without the last week's snapshots |

The dataset caveats in section 4 are mostly about what the failure label measures and
which drives it covers. They limit how far the results generalize, not whether the code
is correct.

## 2. What is done right

**The survival framing matches the textbook method.** `survival.expand` builds
person-period rows, gives a snapshot censored partway through a bin a fractional
weight, and labels an event only in its own bin. This is the discrete-time hazard model of
Singer & Willett and of Suresh et al. 2022 (`suresh-2022-discrete-time-survival-prediction.md`),
fit with a classifier as in survival stacking (`craig-2021-survival-stacking.pdf`). Each
snapshot conditions on the drive being alive on that day. That also handles drives that
were already in service when the panel starts: they enter the risk set at their first
snapshot, with no extra code.

**Censoring at `train_end` fixes the v2 label bug.** A train drive that fails after the
cutoff is censored, not counted as healthy (`panel.snapshots`). The gate recomputes every
label from the cohort, in both directions (`verify.labels_match_cohort`,
`no_visible_failure_labelled_censored`). Tamper tests prove the gate catches the old bug
(`test_gate_catches_v2_label_bug`). Kapoor & Narayanan's leakage taxonomy
(`kapoor-2023-leakage-reproducibility-crisis.md`) lists this kind of temporal label leak,
and the project closes it.

**The splits are stricter than most of the field.** Drives are split by a sha256 bucket,
and test is also later in time (2024+). Calendar date is not a feature, and drive-model
categories come from train drives only. Lu et al. 2020 (`lu-2020-making-disk-failure-predictions-smarter.pdf`)
used random 5-fold cross-validation, which mixes drives and time.

**The sampling weights are honest, and the tempering has a precedent.** Inclusion uses a
salted hash that is independent of the split hash, each drive carries `1/fraction`, and
dense pre-failure days carry weight 1 instead of `stride_days`. Training uses `w^0.5`, and
probabilities are then refit per bin on validation drives with the true weights. Shrinking
extreme weights to accept a little bias for much less variance is established practice
in survey statistics, where it is called weight trimming
(`elliott-2007-bayesian-weight-trimming-glm.pdf`). Fitting calibration with the true
weights is what keeps the probabilities on the real scale.

**The metrics are reimplemented with weights and checked against independent results.**
Weighted AUC and AP are checked against sklearn, Harrell's C against brute force, and
Kaplan-Meier against a hand computation (`tests/test_metrics.py`). Each runs in
O(n log n), and one sort is reused across bootstrap rounds. The bootstrap resamples whole
drives, which is the fix Obuchowski 1997 prescribes for clustered ROC data
(`metricgate-2026-obuchowski-clustered-roc.md`).

**Report sentences are generated from the numbers.** `report._answer` says "SMART adds
information" only when the bootstrap interval of the gain excludes zero, so the report
can't drift from the results the way v2's hand-written claims did.

**The engineering is careful.** Month chunks keep the 646M-row scans within memory. The
memory guard fails before an OOM kill. LightGBM models are saved as text with feature
names, and `load_booster` checks those names against the metadata. Trend windows are
keyed on calendar days, not rows. Every random draw is seeded or hashed.

## 3. What should improve

Each finding gives the evidence, then a fix. Line numbers are at `398f421`.

### R1. The importance figure shows the wrong features (High)

`model.train` sorts `importance_gain` by gain (`steps/model.py:161`), but `write_json`
writes with `sort_keys=True` (`steps/common.py:192`), so the stored dict is alphabetical.
`report.figures` then takes `.head(20)` of that dict (`steps/report.py:107`). The figure
`build-arch/report/importance.png` therefore shows `bin_start, capacity_tb,
days_in_service, model_code, smart_10_raw, smart_10_raw_d30, smart_10_raw_d7,
smart_12_raw, …`, the first names in the alphabet.

The real top features of the full-scale `hazard_smart`, by share of total gain:

| feature | gain |
|---|---|
| bin_start | 20.2% |
| capacity_tb | 10.2% |
| smart_187_normalized | 8.8% |
| smart_197_raw | 8.5% |
| smart_5_raw | 8.1% |
| model_code | 7.7% |
| smart_5_raw_d30 | 4.2% |
| smart_240_raw | 2.8% |

The README's "What matters most" paragraph agrees with this table, not with the figure.
The axis label "share of total gain (top 20)" is also off:
the denominator is the sum of the 20 plotted features, not the total.

**Fix:** in `report.py`, sort before slicing:
`pd.Series(meta_ref["importance_gain"]).sort_values(ascending=False).head(20)[::-1]`, and
divide by the total over all features. A unit test that builds a meta dict and checks the
plotted order would catch a regression.

### R2. Packed SMART 188 values handicap the rule baseline (High)

`smart_188_raw` (command timeout) is read as a raw number, used as a feature, used for
7- and 30-day trends, and included in the rule's `critical_counters`
(`config/study.toml:39`, `:47`). On Seagate drives the raw field holds packed values: 2.9%
of Seagate snapshots have `smart_188_raw >= 65536`, up to 3.4e12, far above any plausible
count of timeouts. Other vendors report 188 as NULL. Seagate packs vendor fields into
other raw values too (attributes 1 and 7, documented in
`ktz-2024-reading-obfuscated-seagate-smart-stats.md` and
`snapraid-daemon-2026-issue-72-seagate-raw-values.md`). For 188 the field layout should be
confirmed with smartctl's `-v 188,raw16` decoding.

The packed values matter most for the rule. `log1p(3e12)` is about 28, so a healthy
Seagate with a packed 188 outranks a drive whose sector counts are rising. With the full
run's predictions:

| | rule as built | rule without 188 | hazard_smart |
|---|---|---|---|
| validation false-alarm budget taken by packed-188 snapshots | 89% | – | – |
| failing test drives alerted in the last 30 days (of 1,784) | 661 (37%) | 1,062 (60%) | 1,379 (77%) |
| alert precision on test | 2.0% | 3.0% | 4.2% |
| false-alarm rate on test (budget 1%) | 1.47% | 1.80% | 1.63% |
| 30-day ROC-AUC | 0.821 | 0.823 | 0.875 |

ROC-AUC barely moves, because packed values are rare. At a fixed false-alarm budget,
though, the rare high scores decide the threshold. The model still beats the rule, but by
317 drives, not 718.

**Fix:** decode 188 or drop it. Either mask the raw value to its low 16 bits once the
layout is confirmed, or move 188 to `features.normalized`. Remove it from
`critical_counters` in any case. Then audit the other raw attributes for the same pattern,
`240`, `241` and `242` first.

### R3. No code path tests label circularity (High)

Backblaze's failure label is an operator decision, and its own SMART post says a non-zero
raw 5, 187, 188, 197 or 198 is "a reason to investigate"
(`backblaze-2016-what-smart-stats-tell-us.md`). Features that trigger the label are
partly restating it. In the full model, those five counters and their trends account for
37.4% of total gain.

Splitting the 1,784 failing test drives by whether any of the five counters was ever
non-zero in their test snapshots:

| positives in the 30-day test set | failing drives | hazard_smart | hazard_nosmart | rule |
|---|---|---|---|---|
| all | 1,784 | 0.875 | 0.602 | 0.821 |
| counters never non-zero ("silent") | 349 (19.6%) | **0.627** | 0.540 | 0.464 |
| counters non-zero at some point | 1,435 | 0.936 | 0.618 | 0.908 |

Each row keeps the same healthy negatives. On silent failures the model keeps some signal
(0.627, against 0.540 for the model without SMART), but most of the headline AUC comes
from drives whose counters rose. The same split appears in the literature: Pinheiro et
al. found 36% of Google's failed drives had zero counts on every SMART variable
(`pinheiro-2007-failure-trends-large-disk-population.pdf`). "Silent" here treats NULL as
zero, and most non-Seagate drives report 187 and 188 as NULL (section 4, D2), so the
silent group is defined by 5, 197 and 198 for those vendors.

**Fix:** a small code change, which the "only when necessary" rule allows because no
existing step can answer the question.
- `model.model_features` accepts only `all`, `context` or `smart` (`steps/model.py:40`).
  Give it an `exclude` list and add a `train_hazard_nocritical` step that drops the
  critical counters, their normalized values and their trends.
- Have `evaluate` report a silent-failure slice next to the full one.
- Present the full model's gain as an upper bound on what SMART adds.

### R4. The last days before failure carry the precision metrics (Medium)

Backblaze marks the drive's last day with `failure = 1`, and that day's snapshot is kept
(duration 0). The SMART values recorded that day may already show the breakdown the
operator acted on. Of the weight of 7-day test positives, 15.3% comes from failure-day
snapshots and 29.4% from duration 0 or 1.

Dropping positives close to failure (negatives unchanged):

| test set | hazard_smart AUC / PR-AUC | binary_30d | rule |
|---|---|---|---|
| 30 d, all positives | 0.875 / 0.127 | 0.879 / 0.118 | 0.821 / 0.027 |
| 30 d, positives ≥ 7 days out | 0.866 / 0.080 | 0.870 / 0.074 | 0.812 / 0.017 |
| 30 d, positives ≥ 14 days out | 0.859 / 0.050 | 0.864 / 0.047 | 0.806 / 0.011 |

AUC holds up well. PR-AUC falls faster than the base rate: the base rate falls 23% and
46% in the two cuts, PR-AUC 37% and 61%. Some of the drop is mechanical, since PR-AUC
scales with prevalence, but the rest shows that the model's most confident alerts
cluster in the last week. The per-drive recall has the same issue in milder form: 14% of
the 1,379 alerted failing drives got their first alert less than 7 days before failure,
and 5.4% only on the last day or the failure day (`evaluate.alerting`,
`steps/evaluate.py:206`).

**Fix:** add a `min_lead_days` parameter to `evaluate` (say 7) and report each metric
with and without it. Count a failing drive as detected only if an alert came at least
that many days before failure.

### R5. Validation drives do three jobs (Medium)

The validation buckets (70-79) are used for early stopping (`model.train`), for the
per-bin Platt fit (`model.calibrate`), and for the alert threshold
(`evaluate.alerting`). Each reuse makes the next one slightly optimistic, and the
threshold is chosen on scores that were calibrated on the same rows. The 1% budget coming
out at 1.63% on test is mostly drift (ISSUES #9), but part may be this reuse.

`fit_platt` also leaves the slope free. The docstring says ranking is unchanged "when
b > 0", but nothing checks it. All 30 fitted slopes in the medium and full runs are between 1.08
and 1.42, so it holds today. A sparse long bin at a smaller scale could flip a slope negative
and silently reverse the ranking within that bin.

**Fix:** split validation into two bucket ranges (early stopping, then calibration and
threshold), or cross-fit. In `calibrate`, raise an error when `b <= 0`.

### R6. The context-only ablation cannot see the true age of older drives (Medium)

`days_in_service` counts from the drive's first row in the panel
(`steps/panel.py:180`), and the panel starts on 2016-01-01. Backblaze's data starts in
2013, so a drive installed before 2016 looks new on its first day here. In the full
cohort, 16.5% of train and 16.8% of validation drives first appear on 2016-01-01, against
1.9% of test drives. The true age is in `smart_9_raw` (power-on hours), but that column
is in the `smart` group, so `hazard_nosmart` never sees it.

The "SMART gain" therefore includes knowing the true age, which is context, not health
signal. `smart_9_raw` has only 1.0% of the full model's gain, so the effect is probably
small. Still, the baseline the gain is measured against is weaker than it looks, and the
train and test populations differ on this point.

**Fix:** run the ablation with `smart_9_raw` moved into `context`, or derive age from
`smart_9_raw` for the context model. Add a flag feature for left-truncated drives, or
start their `days_in_service` from power-on hours.

### R7. Horizon metrics drop censored rows without reweighting (Medium)

`discrimination`, the Brier score and the alerting metrics keep only snapshots whose
status at the horizon is known (`known_status >= 0`, `steps/evaluate.py:80`). That is
unbiased only if censoring is unrelated to risk. Censoring at the panel end is unrelated.
Retirement probably is not (ISSUES #7). Uno et al. 2011 (`uno-2011-c-statistics-censored-survival.md`)
and Vock et al. 2016 (`vock-2016-ipcw-machine-learning-censored-ehr.md`) use
inverse-probability-of-censoring weights (IPCW) instead. The calibration table already
compares predictions with Kaplan-Meier, so it handles this correctly.

The concordance has related problems: Harrell's C, computed on a random 300k-row sample
(`steps/evaluate.py:307`), with no interval. The earlier reviews covered this.

**Fix:** estimate the censoring survival G(t) with Kaplan-Meier on the test snapshots and
weight known-status rows by `1/G`. That costs one function in `metrics.py`. Replace or
supplement Harrell's C with Uno's C, sample by drive, and bootstrap it.

### R8. Alerting has one operating point and no intervals (Medium)

`alert_false_alarm_rate` is a single scalar (0.01). Production reports in the reviewed
literature also use 0.3% (Alibaba, StreamDFP) and 0.1% (Microsoft). At a 0.12% base
rate, a 1% false-alarm rate caps precision at about 11% even with perfect recall, so the
1% point alone can't show whether the model is usable in practice. The alert metrics
(recall, precision, drives alerted) also get no bootstrap interval, unlike the AUCs.

**Fix:** make the budget a list (`[0.001, 0.003, 0.01]`) and run the existing drive-level
bootstrap over the alert summary.

### R9. scipy is used but not declared (Low)

`survival.fit_platt` imports `scipy.optimize` (`steps/survival.py:86`). scipy is not in
`pyproject.toml` or in the `requires` of the train steps. It is installed only because
scikit-learn depends on it. The gwen review suggests moving scikit-learn to the dev
group, since only tests use it. Doing that would break training.

**Fix:** declare `scipy` in `dependencies` and in the `requires` of `train_*`.

### R10. The tests can't catch problems that need real-data quirks (Low)

The synthetic panel's only failure signal is a rising `smart_5`, every vendor reports
every column, and no raw value is packed. That is why R1 to R4 pass the suite. None of
`evaluate.alerting`, `evaluate.life`, `evaluate.calibration` or the report figures has a
direct unit test.

**Fix:** add to `tests/synth.py` a Seagate-like model with packed 188 values, vendors with
NULL 187/188, and a group of failing drives with no SMART signal. Add unit tests for
`alerting` (threshold from validation only, per-drive recall) and for the importance
ordering.

### R11. Smaller points (Low)

- `verify.snapshot_weights_valid` (`steps/verify.py:127`) accepts either weight on any
  row. It could check that weight 1 occurs only on dense days.
- `drive_index` computes `n_models_per_month`, but nothing reads it. It is 0 for every
  drive today. A gate check would keep it that way.
- `in_dense` uses the failure date even when that failure is after `train_end`
  (`steps/panel.py:188`), so the sampling of a few late-2023 train rows depends on 2024
  information. The weights correct for it and no label leaks. Restricting dense days to
  failures that are visible in the split would make the design easier to explain.
- `TRY_CAST` turns unparseable strings into NULL without counting them. Logging the count
  per column in `extract` would expose upstream format changes.
- `explore.feature_signal` ranks missing values last. Because 187 and 188 are NULL for
  three of the four vendors, their single-feature AUCs partly measure "is this a
  Seagate".

## 4. Dataset caveats and limitations

These are properties of Backblaze's panel. Each should be stated next to any result.

**D1. The failure label is an operator decision, partly triggered by SMART.** Backblaze
records a failure when it replaces a drive for failing. Its own process starts
investigations on non-zero 5, 187, 188, 197 or 198 (`backblaze-2016-what-smart-stats-tell-us.md`).
The label is therefore partly a function of the features, so the SMART gain is an upper
bound (R3). Labels in the Google and EMC studies are also replacement decisions, but with
different triggers, which makes cross-study comparisons of AUC loose.

**D2. Attribute coverage differs by vendor.** In the full cohort's snapshots, 187 and 188
are NULL for almost 100% of HGST, Toshiba and WDC rows and present for 98.8% of Seagate
rows. A "critical counter" therefore means five attributes on a Seagate and three on
everything else. `smart_187_normalized`, the third most important feature, is in effect a
Seagate-only signal. Results per vendor would show how much of the SMART gain transfers.

**D3. Some raw values are vendor-packed.** Seagate packs several fields into the raw
values of 1 and 7 (handled: the project uses the normalized values) and, from the
evidence in R2, 188. 240-242 are candidates. Differences of packed values, which the d7
and d30 trend features compute, have no physical meaning.

**D4. One operator, four vendors, a fleet chosen by price.** Every drive sits in
Backblaze's pods, under Backblaze's workload, cooling and replacement policy. Many are
consumer models running in a data center. The model mix follows purchasing: drive models
the train set does not know ("other") are 1.8% of train weight and 5.0% of test weight.
Seagate has publicly disputed Backblaze's failure figures
(`hexus-2015-seagate-disputes-backblaze.md`), and Olds 2014 criticized comparisons across
drives of different ages and workloads (`olds-2014-how-not-to-evaluate-hdd-reliability.md`).
The SMART signal does replicate at Google (Pinheiro 2007) and EMC (`ma-2015-raidshield.pdf`),
but a model trained here should not be expected to transfer as-is to another fleet.

**D5. The panel is left-truncated at 2016-01-01.** One sixth of train drives were already
in service on day 1 (R6). The snapshot-conditional model handles their delayed entry
correctly, but any feature that counts time from the first row understates their age.

**D6. Retirement is censoring, and it may depend on risk.** Drives that leave without a
failure row are censored (ISSUES #7). If Backblaze retires suspicious drives early,
failures are undercounted, more so in later years. This is the most plausible
explanation of the 2025 drift (ISSUES #9). The data can't separate the two causes, but
the 2023+ fields below can at least show whether retirements cluster in particular pods.

**D7. Location fields exist only from 2023.** `datacenter`, `cluster_id`, `vault_id`,
`pod_id` and `pod_slot_num` are empty before 2023. `datacenter` is filled for 52% of 2023
rows, 94.5% of 2024 and 100% of 2025, and `pod_id` for 77%, 100% and 100%. They can't be
features over the study period, but they cover the whole test window. Failures cluster by
pod and by purchase batch, so a pod-level bootstrap on test would give more honest
intervals than the drive-level one. The same fields support the failure-burst audit
proposed in the research report.

**D8. Some days are missing or partly missing.** 2017-01-30 and 2022-12-10 have no rows.
2017-01-28, -29 and -31 have 46 to 61 rows against about 73,700 on nearby days. Ten more
days have under 90% of their neighbors' row count; the largest drops are 2017-11-14
(33,644 vs 91,162), 2018-10-24, 2019-11-05, 2022-06-06, 2023-04-13 and 2023-04-16 (about
72,000 vs 241,000). The date-keyed trend windows tolerate gaps. The data can't show whether
failures on the missing days were recorded later or lost.

**D9. The failure day and re-deployed serials.** `failure = 1` marks the last day the
drive reported, and its SMART values may already show the failure (R4). 561 cohort drives
keep reporting after their first failure row. The pipeline cuts them at the first
failure, which is correct, but it means a serial number does not always identify one
physical lifetime.

**D10. SMART is a small window on drive health.** The panel has one row of SMART
attributes per drive-day: no workload, no SCSI or SAS error logs, no `smartctl -l error`
entries, no reallocation events within a day. Under this project's definition, 19.6% of
failing test drives never show a non-zero critical counter. Pinheiro's 36% (zero counts
on all SMART variables) suggests the true share of silent failures is higher. No model
built on this panel can predict those failures much better than chance.

**D11. The fleet grows, and test drives are much larger.** Drives reporting per year
grew from 81,173 in 2016 to 349,462 in 2025, and panel failure rows from 1,428 to between
4,300 and 4,700 a year in 2023-2025. Drive-day weights handle the counting. The capacity
mix is a bigger problem: drives of 16 TB or more are 9.7% of train snapshot weight and
49.3% of test weight (mean 9.5 TB against 14.6 TB). `capacity_tb` is the model's second
most important feature, and gradient-boosted trees predict flat beyond the range they
were trained on, so half the test set sits where the model saw few examples. This covariate
shift is a second candidate explanation for the drift in D6, next to retirement.

## 5. Points already raised in the other reviews

These still stand, and this review does not repeat their analysis:

- The README points to `build/` for full-scale results that are in `build-arch/` (flint F1).
- `DURATION_BUCKETS` duplicates `label.bin_edges` (flint F3).
- `enough_failures_*` is always registered as a warning (flint F2).
- The `duckdb>=1.5` floor is below the steps' `>=2.0` (flint F4).
- Trend features use the earliest value in the window, not the value at its start (gwen 3.7).
- The concordance ranks by −RMST (gwen 3.5).
- Cross-horizon AUCs come from different calendar cohorts (gwen 3.6).
- Dense pre-failure rows before `test_start` are trimmed for early test failures (gwen 3.8).
- There is no CI, and the dataset version is not pinned (gwen 3.1, 3.8).

## 6. Recommended order of work

1. R1: sort the importance figure (one line in `report.py`).
2. R2: decode or drop `smart_188_raw`, remove it from `critical_counters`, and rerun. The
   rule comparison in the README will change.
3. R3 and R4: add the no-critical-counter model, the silent-failure slice and
   `min_lead_days`. Together they bound how much of the result is label circularity.
4. R7 and R8: IPCW for horizon metrics, Uno's C with a drive bootstrap, and a list of
   false-alarm budgets with intervals.
5. R5 and R6: separate the validation roles and give the context model true age.
6. R9 to R11: declare scipy, extend the synthetic panel, and clean up the small points.
7. Per-vendor results (D2) and a pod-level bootstrap on test (D7), once the above is
   done.

Items 2 and 3 change the headline numbers, so rerun the medium scale first and the full
scale on the 31 GB machine afterwards.

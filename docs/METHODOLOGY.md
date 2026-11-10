# Methodology

The question: **from a drive's `smartctl` readings today, can we say how likely it is to
fail, and roughly when?** This page explains how v3 answers it and why each choice was
made. The code is the reference. Each section names the step that implements it.

## 1. Data

Backblaze's public drive-stats panel: one row per drive per day with the SMART
attributes `smartctl` reports, plus `failure = 1` on a drive's last operational day.
2016-01-01 to 2025-12-31, 646,777,037 rows, 478,464 serial numbers, 26,679 drives with
a failure row. `drive_index` checks the file's sha256 against the value pinned in
`pipeline.toml` before scanning, so a changed download can't silently change the data.

Quirks handled (`drive_index`, `cohort`, `extract`):

| Quirk | Handling |
|---|---|
| Boot SSDs in the panel | Excluded by a model-name pattern (`study.toml: data.ssd_model_pattern`) |
| Model names differ in whitespace across years (`WDC  WUH721414ALE6L4`) | Whitespace normalised. The first name a drive reports wins, so the feature never depends on later rows (7 drives change model string mid-life, e.g. `HGST HMS5C4040ALE640` to `...BLE640`). Drives that report more than one model in a month are counted, and the gate warns about them |
| Capacity jitters by a few MB, on 2018-02-25 alone every drive reports a rounded value (4,000,790,000,000 instead of 4,000,787,030,016), new drives report -1 on their first day, and 10 drives never report one | The first valid capacity, rounded to 10 GB, so the feature does not depend on how long the drive lives (a lifetime maximum leaked survival past 2018-02-25). A first-day snapshot takes the next day's value: capacity is a nameplate fact known at install. Drives that never report one get their model's most common capacity; a NULL would mark them, since all 10 fail within days. That mapping counts all drives of the panel, which is safe here only because each model has a single rounded capacity |
| Same-day duplicate rows | One row per drive-day: the most complete row, then the first filename |
| Drives keep reporting after a failure. Measured on the panel: 710 drives (694 HDDs, 16 boot SSDs) have rows after their first failure row, 46 have two failure rows, and 561 of them are in the full-scale cohort | The first failure is the event, and rows after it are dropped |
| Many SMART columns stored as VARCHAR | `TRY_CAST` to DOUBLE. Strings that fail the cast are counted per column and returned by `extract` (0 at medium scale, 11,775,008 rows) |
| Vendor-packed raw values (SMART 188 and 240 on Seagate) | 188: the normalized value replaces the raw one. 240: the raw value keeps its low 32 bits (§5) |
| Reporting gaps | All windows are keyed on dates, not rows |

## 2. The question as a survival problem

v2 asked "will this drive fail within 30 days?" That's a yes/no question, and it can't
say *when*. It also forces a decision for every row near the end of the observed data:
a drive seen on its last day might or might not fail next week. v2 labelled such rows
"healthy", which is wrong (review §3.2).

v3 treats it as **time-to-event with right censoring**. For every snapshot (a drive on a
given day) the label is:

- `duration_days`: days until the first failure (`event = 1`), or until the last day
  the drive is known to be alive (`event = 0`, censored);
- training drives are censored at `train_end`. A failure after the cutoff is *unknown*
  to training, not "healthy".

The model is a **discrete-time hazard model** (`model.py`, `survival.py`). The future
after a snapshot is cut into bins (`[0,7), [7,14), [14,30), [30,60), [60,90), [90,180),
[180,365)` days, `label.bin_edges`). Each snapshot becomes one row per bin it is at risk
in ("person-period" rows), and a LightGBM classifier learns

    h_k(x) = P(fail in bin k | alive at the start of bin k, features x)

with the bin start as an extra feature. The survival curve is
`S(t_k) = prod_{j<=k} (1 - h_j)`, from which:

- `P(fail within H days) = 1 - S(H)` for H = 7, 30, 90, 180, 365;
- the **median remaining life** (where S crosses 50%) and a **10-90% interval**;
- the **restricted mean**: expected days alive within the next year.

A snapshot censored inside a bin contributes that bin with weight equal to the observed
fraction (actuarial adjustment). Dropping it would bias hazards up, and counting it as a
full survival would bias them down. The expansion is fed to LightGBM in batches
(`ExpandedSequence`), never materialised.

## 3. Splits

- **By drive**: a sha256 bucket of the serial number (stable across library versions)
  puts 70% of drives in train, 10% in validation, 20% in test. No drive is in two splits.
- **By time**: train/validation snapshots are on or before 2023-12-31, and test
  snapshots are from 2024-01-01. Trend features on early test days may look back into
  December 2023 *of the same test drive*, which is the drive's own past.
- **Validation drives have two roles**, assigned by a second stable hash
  (`split.calibration_share = 0.5`). One half drives early stopping. The other half fits
  the probability calibration (§4) and sets the alert thresholds (§7). The calibration is
  therefore not fitted on the rows that chose the number of trees.
- **Test drives** are used once, for the final numbers.

## 4. Sampling and weights

The full panel is about 650M drive-days. Expanded into survival rows it would need
hundreds of GB. v3 samples, and keeps every estimate unbiased with **inverse-probability
weights** (`cohort`, `snapshots`):

- drives that fail at some point are kept with probability `failing_fraction`, all
  others with `healthy_fraction` (weight = 1 / fraction);
- within a drive, a snapshot every `stride_days` (weight `stride_days`), plus **every**
  day in the `dense_days` before a failure (weight 1), so the run-up to a failure is seen
  in full detail.

Dense days are kept only before a failure that is **visible in the split**. A train
drive that fails after `train_end` gets stride snapshots only, so its sampling does not
depend on what happens after the cutoff. Test snapshots start at `test_start`, so for a
drive failing in early 2024 the dense days before 2024-01-01 are not scored. This is by
design: those days belong to the training era.

Every metric uses these weights, so a "base rate" or a precision in the report is the
real-world value (about 0.004% of drive-days are a failure day), not the
enriched sample's. The weights do not correct ROC-AUC for prevalence: AUC doesn't change
when every row of a class gets the same weight. They change the mix of drives and days
within each class, and they make PR-AUC, precision, the base rate and calibration
real-world quantities. v2's demo used only failing drives, which taught "how close to
failure" instead of "will it fail" (review §4.5).

### Training weights and calibration

Training with the full weights works badly. At the small scale a healthy drive-day
weighs ~70x a failure row, the effective sample is tiny, and early stopping fires after
~30 rounds with the model barely off the base rate. On validation drives, training with
**weights^0.5** (`weight_power` in `pipeline.toml`) raised 30-day ROC-AUC from 0.85 to
0.89 and nearly doubled PR-AUC. Two sensitivity steps report other powers on test
(`hazard_smart_w075`, `hazard_smart_w100`). They are reported, not used to choose the
power. At medium scale 0.75 ranks like 0.5 at 30 days, and 1.0 ranks worse and stops at
iteration 11.

Tempered weights distort the probability scale, and every variant was over-confident at
long horizons: a high-risk snapshot gets a high hazard in every future bin, so its
survival curve collapses too fast. Both are fixed by **per-bin Platt recalibration**:
after training, a two-parameter logistic fit `h = sigmoid(a_k + b_k * raw_logit)` per
bin on the calibration half of the validation drives, with the *true* weights. On
held-out validation drives this moved the top risk decile's predicted 1-year failure
probability from 0.56 to 0.33 against an observed 0.30, without changing the ranking.
Coefficients are stored in each model's metadata JSON and applied by `predict`.

- **Slope guard.** A slope `b_k <= 0` would reverse the ranking inside bin k. That can
  happen in a bin with very few validation failures. Such a bin is refitted with the
  slope fixed at 1, so only the level moves, and the bin is recorded under
  `calibration_notes.fixed_slope_bins`. At medium scale no bin needed it, and the slopes
  of `hazard_smart` are 1.2-1.5.
- **Recent recalibration.** `hazard_smart` also stores a second calibration fitted only
  on calibration snapshots from the last `split.recent_days` (365) before `train_end`,
  i.e. 2023. `predict` scores it as `hazard_smart_recent`: the same trees with those
  coefficients. A bin without a failure in that year keeps the full-period fit
  (`calibration_recent_notes.fallback_bins`). It tests whether recent failure rates
  explain the test-year drift (§7.6).

## 5. Features

Fixed in `study.toml` (not chosen from the data, so the schema never depends on the
sample, review §4.5) and stored in `build/feature-schema.json`. 64 features:

- **SMART values**: 23 raw attributes populated on HDDs (5, 9, 187, 197, 198, ...) and 10
  normalized values. For 1, 3, 7 and 188 the raw value is vendor-packed, so only the
  normalized value is used. 5, 187, 197 and 198 have both.
  - **18, 23 and 24**: the raw value is a placeholder, always 0 (checked on the whole
    panel: 131.8M rows for 18, 129.7M for 23 and 24). The signal, if any, is in the
    normalized value. 24 (mostly Toshiba) leaves 100 on 99 of 117,848 drives (28 in train,
    25 of them failing) and 23 on 11 (one in train). Both enter as normalized values: it is
    little data, kept because it does no harm. 18 never leaves 100 (131.8M rows), so it is
    not a feature. (Until 2026-11-09 all three entered as raw columns and triggered the
    gate's `features.constant` warning. At small scale 23 can still be constant in train.)
  - **188 (command timeout)**: Seagate packs several 16-bit fields into the raw value
    (2.9% of Seagate snapshots are >= 65536, up to 3.4e12) and the other vendors report
    NULL. The raw value and its trends are not features.
  - **240 (head flying hours)**: Seagate stores a milliseconds field above bit 32
    (smartctl's `msec24hour32` format, 1.1% of Seagate snapshots >= 2^32).
    `features.raw_low_bits` keeps the low 32 bits. 241 and 242 were checked and are clean.
- **trends**: for 12 counters that grow as a drive degrades, `*_d7` and `*_d30` = the
  value now minus the earliest non-null value of that attribute within the last 7 / 30
  calendar days (a date-keyed `RANGE` window). `window_days_7` and `window_days_30` are
  the span from the earliest row of any kind in that window to today. They don't skip
  rows where the specific attribute is NULL, so for an attribute with gaps the span can
  be longer than the one its trend was computed over;
- **context**: `days_in_service`, `left_truncated`, capacity, drive model (top 30 by
  *train* drives, else "other") and vendor, as LightGBM categoricals.
  `days_in_service` counts the days the drive has been observed in the panel, from its
  first row. `left_truncated = 1` when that first row is the panel's first day, so the
  drive was already in service and its real age is unknown (16.5% of train drives at
  medium scale).

The **critical counters** behind the rule baseline, the silent-failure slice and
`hazard_nocritical` are the raw values of 5, 187, 197 and 198
(`features.critical_counters`). 188 is left out: its packed Seagate values took 89% of
the rule's validation false-alarm budget in the full-scale run of 2026-10-24.

Calendar date is **not** a feature (review §4.1). Drive age comes from SMART 9
(power-on hours) and days in service.

## 6. Is it SMART that helps? The comparisons

| Model | What it is | Why it is there |
|---|---|---|
| `hazard_smart` | survival model, SMART + context | the model under test |
| `hazard_nosmart` | same model, context only | **ablation**: what you know without `smartctl` metrics. The gain over this is the answer to the project's question |
| `hazard_nocritical` | SMART + context without 5, 187, 188, 197, 198 (raw, normalized, trends) | **label circularity**: Backblaze replaces drives when these counters rise, so they partly define the failure label. This is a sensitivity check, not a clean split: removing the counters also removes physical signal, and the remaining features can still correlate with them |
| `hazard_usage` | context + usage counters 4, 9, 12, 193, 240, 241, 242 | tests whether SMART helps only because it measures age and wear (power-on hours give the true age of left-truncated drives) |
| `hazard_smart_w075`, `hazard_smart_w100` | `hazard_smart` with training weight power 0.75 / 1.0 | sensitivity to the weight power (§4) |
| `hazard_smart_recent` | `hazard_smart`'s trees, calibrated on 2023 only | does a recent recalibration remove the drift? (§7.6) |
| `binary_30d` | fails-within-30-days classifier | the v2-style baseline, done correctly |
| `rule_counters` | sum of `log1p` of the critical counters 5, 187, 197, 198 | the classic rule of thumb, no training |

Ablations use `include` / `exclude` glob patterns on the feature groups (`model.train`).
A pattern that matches no feature is an error.

## 7. Evaluation (`evaluate`)

All on test drives, all weighted. **Units**: discrimination, calibration, false alarms
and precision are per drive-day snapshot. The "failing drives alerted" counts and the
per-drive ROC-AUC are per drive.

### 7.1 Discrimination

- **ROC-AUC and PR-AUC per horizon**, on snapshots whose status at the horizon is known.
  PR-AUC matters because failures are rare: a high ROC-AUC can still mean most alerts
  are false.
- **The same with IPCW**: instead of dropping snapshots whose status is unknown,
  inverse-probability-of-censoring weights scale up comparable known ones (a weighted
  Kaplan-Meier of the censoring time). At medium scale the two differ by 0.001-0.013.
- **Per-drive ROC-AUC**: one random snapshot per drive, weighted per drive, so drives
  with many snapshots don't dominate. The point estimate averages 20 draws.
- **Brier score and Brier skill** = 1 - Brier / Brier of always predicting the base rate.
  At these base rates the skill is small (0.042 at 30 days in the final full run) and says little.
- **The 365-day caveat.** A horizon of H days needs H days of follow-up to know that a
  drive survived it, and the panel ends 2025-12-31. The 365-day row uses roughly the 2024
  snapshots only, so the horizons are measured on different calendar cohorts and are not
  a like-for-like trend. The report says so under the table.

### 7.2 Intervals

**95% intervals from a stratified drive-level bootstrap**: drives are resampled, not
rows, and failing and healthy drives are resampled separately, as they were sampled.
Daily snapshots of one drive are nearly identical, so row-level resampling makes
intervals far too narrow (review §4.3). Differences against the reference model
(`hazard_smart`) are bootstrapped as paired differences on the same rounds, with the
share of rounds in which the reference is not better. 200 rounds, 50 for concordance.

### 7.3 Slices

The ranking metrics on parts of the test set. Positive-side slices keep every
known-healthy snapshot and restrict the failing ones; population slices restrict both.

- **positives >= 7 days before failure** (`evaluation.min_lead_days`): the last days'
  SMART values may already show the breakdown the operator acted on;
- **silent failures**: drives that fail with none of the critical counters above zero
  in any test snapshot, and the complementary "failures with a critical counter above
  zero";
- at 30 days only: **per vendor**, **capacity >= / < 16 TB**
  (`evaluation.capacity_split_tb`: large drives are about 10% of train weight and 50% of
  test weight), and drives in service before the panel starts vs first seen after.

### 7.4 Concordance

Harrell's C and Uno's C (truncated at 365 days, each failure weighted by the inverse
squared censoring survival) between a risk score and the actual time to failure. Drives
are sampled whole up to `concordance_max_rows` (300,000), so at medium scale every test
snapshot is used. Hazard models are scored by minus their restricted mean and also by
their 30-day risk, so they can be compared with the classifier on the same kind of score.

### 7.5 Calibration and early warning

- **Calibration**: mean predicted vs Kaplan-Meier observed failure probability per risk
  decile. Kaplan-Meier handles censored snapshots.
- **Alert budgets**: thresholds are set on the calibration half of the validation drives
  so that 0.1%, 0.3% or 1% of healthy drive-days raise an alert
  (`evaluation.alert_false_alarm_rates`; 1% is the main budget). On test, with
  intervals: the false-alarm rate, precision, the share of failing drives alerted in
  their last 30 days, the share alerted at least 7 days before failure, and detection by
  days before failure.
- **Unknown-outcome alerts**: an alert whose 30-day outcome is unknown (the panel ends
  first) is left out of precision. Its share is reported, together with a precision that
  counts those alerts as false.
- **Remaining life, timing**: among snapshots whose predicted 10% / 50% / 90% failure
  day is within a year, the share that actually failed by that day (targets 10/50/90%).
  Shares are of weighted snapshots. A snapshot censored before its outcome is known is
  left out, which favours snapshots with an early day, so the headline share is IPCW: a
  known failure is weighted by 1 / P(uncensored on its failure day), a known survivor by
  1 / P(uncensored the day before its predicted day), from one Kaplan-Meier curve of the
  censoring time. That is unbiased only if censoring is unrelated to both the failure
  time and the predicted day. Most censoring is the panel's end, which depends on the
  snapshot date, so it is an adjusted estimate, not an exact one. The known-outcome share
  is reported next to it. Neither corrects for retirement related to health (§9).
- **Remaining life, visibility**: for drives that do fail within a year, how often the
  predicted median is within a year, by how far away the failure really was. (Coverage
  of an interval *conditional on failing* is not a calibration measure: a perfect model
  can't reach 80% on it, so it is not reported.)

### 7.6 Drift

Mean predicted vs observed 30-day risk per split and calendar year, with a drive
bootstrap interval for the ratio. Validation drives share the training era, so a gap
that appears only in the test years is drift, not a fitting error. Per model, `evaluate`
records the band of the validation-year ratios, whether the last validation year (2023)
already leaves the band of the earlier years (a warning that needs no test data), and
which test years fall outside the band. The step log prints a `DRIFT` line for each model
with a flagged year. The same table for `hazard_smart_recent` shows whether recalibrating
on 2023 helps. At medium scale it doesn't.

### 7.7 Retirement

For each split and year Y, drives that never fail and have snapshots in Y are split into
those that stop reporting before the end of Y+1 (left) and those still reporting
(stayed). If leaving were unrelated to health, as the censoring assumption says, both
groups would carry about the same predicted 30-day risk in Y. The report gives the ratio
left / stayed and the share above the main alert threshold. The ratio has no interval:
read it as a direction, not a test. At medium scale it is above 1 in every split-year.

## 8. The verification gate (`verify`)

Runs before any training and stops the pipeline on any error. 56 checks at full scale; 14 more are skipped as not applicable, with the reason for each in the verification report. It recomputes
every label from the cohort independently (both directions: no failure inside the window
labelled healthy, no healthy row labelled failing), and checks drive and time
disjointness of the splits, weights against the sampling config, the stable-bucket
split, no snapshot after a failure, the column schema, leak columns, feature fill, and
that the model categories come from train drives only. Four checks were added in the
audit:

- `stride_rows_on_stride_days` (error): rows with the stride weight sit on the drive's
  stride day, so a sampler that keeps weight 7 but samples at another density fails;
- `dense_rows_before_visible_failure` (error): weight-1 rows only within `dense_days`
  before a failure visible in the split;
- `cohort_drives_have_snapshots` (warning): cohort drives without any snapshot, which is
  expected only for drives with fewer rows in their split window than the stride (3 at
  medium scale, 16 at full scale, each with 1-2 rows);
- `one_model_per_drive` (warning): drives reporting more than one model in a month.

`enough_failures_*` warns below `evaluation.min_failing_drives` (30). A test also checks
that snapshot features computed on a panel cut at a date equal those computed on the
full panel (no look-ahead). The report is `build/verify-report.json`.

## 9. Limits

- **Retirement is probably informative censoring.** Backblaze retires drives without
  failing them. At medium scale, drives that leave carry 2-9x the predicted risk of
  drives that stay in every validation year but 2019 (1.06), and 3.3x in 2024 (§7.7). So
  retirement is related to predicted health, and the observed failure risk is likely
  too low. The check does not say how many retired drives would have failed, so the size
  of that bias is unknown. Treating "leaves the panel" as an event of its own was not
  tried.
- **Training noise is not in the intervals.** Each model is trained once, and the
  drive-level bootstrap only resamples test drives. Two full runs that differed in 10
  of 7.6 million training snapshots moved the 30-day ROC-AUC by 0.002 and the
  survival-minus-classifier difference from -0.006 [-0.009, -0.002] to -0.001 [-0.004,
  +0.002]. Differences of a few thousandths between models are
  ties.
- **Label circularity.** Backblaze's replacement decisions use counters 5, 187, 188,
  197 and 198, so part of the SMART signal is the operator's policy. `hazard_nocritical`
  measures how much of the gain survives without those counters; it does not separate
  policy from physics, since the counters also carry physical signal: at medium scale about 62% of the SMART gain remains without those counters.
  Silent failures (20% of failing test drives at medium scale) are ranked only a little
  better than chance (ROC-AUC 0.608).
- **The 365-day horizon** is only measurable on test snapshots with a year of follow-up
  (2024 snapshots). Beyond a year the model says "more than a year" and nothing more.
- **SMART semantics vary by vendor and model.** The model learns them per model where it
  has enough drives. Rare models fall into "other". Some raw values are vendor-packed
  (188, 240); any new raw attribute needs the same check.
- **Capacity covariate shift.** Drives of 16 TB and more are about 10% of train weight
  and 50% of test weight, and rank worse (0.830 vs 0.884 at 30 days, medium scale).
- **Drift.** Test-period failure rates are lower than the model expects, and the gap
  grows from 2024 to 2025. Recalibrating on the last pre-test year does not remove it.
  Probabilities need recalibration on recent data before use, and a rolling-origin
  evaluation has not been done.
- **Results are for Backblaze's data-centre workload.** A desktop drive's environment
  differs.

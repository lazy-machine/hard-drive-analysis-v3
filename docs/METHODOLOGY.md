# Methodology

The question: **from a drive's `smartctl` readings today, can we say how likely it is to
fail, and roughly when?** This page explains how v3 answers it and why each choice was
made. The code is the reference. Each section names the step that implements it.

## 1. Data

Backblaze's public drive-stats panel: one row per drive per day with the SMART
attributes `smartctl` reports, plus `failure = 1` on a drive's last operational day.
2016-01-01 to 2025-12-31, 646,777,037 rows, 478,464 serial numbers, 26,679 drives with
a failure row.

Quirks handled (`drive_index`, `cohort`, `extract`):

| Quirk | Handling |
|---|---|
| Boot SSDs in the panel | Excluded by a model-name pattern (`study.toml: data.ssd_model_pattern`) |
| Model names differ in whitespace across years (`WDC  WUH721414ALE6L4`) | Whitespace normalised. The latest name wins |
| Same-day duplicate rows | One row per drive-day: the most complete row, then the first filename |
| 664 drives keep reporting after a failure, 46 have two failure rows | The first failure is the event, and rows after it are dropped |
| Many SMART columns stored as VARCHAR | `TRY_CAST` to DOUBLE |
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
[180,365)` days). Each snapshot becomes one row per bin it is at risk in
("person-period" rows), and a LightGBM classifier learns

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
- **Validation drives** are used for early stopping and for choosing the alert
  threshold. The test drives are used once, for the final numbers.

## 4. Sampling and weights

The full panel is about 650M drive-days. Expanded into survival rows it would need
hundreds of GB. v3 samples, and keeps every estimate unbiased with **inverse-probability
weights** (`cohort`, `snapshots`):

- drives that fail at some point are kept with probability `failing_fraction`, all
  others with `healthy_fraction` (weight = 1 / fraction);
- within a drive, a snapshot every `stride_days` (weight `stride_days`), plus **every**
  day in the `dense_days` before a failure (weight 1), so the run-up to a failure is seen
  in full detail.

Training and every metric use these weights, so a "base rate" or a precision in the
report is the real-world value (about 0.004% of drive-days are a failure day), not the
enriched sample's. v2's demo used only failing drives, which taught "how close to
failure" instead of "will it fail" (review §4.5).

## 5. Features

Fixed in `study.toml` (not chosen from the data, so the schema never depends on the
sample, review §4.5) and stored in `build/feature-schema.json`:

- **SMART values**: the raw attributes populated on HDDs (5, 9, 187, 188, 197, 198, ...)
  and the normalized value where the raw one is vendor-packed (1, 3, 7);
- **trends**: `x - (earliest x in the last 7 / 30 calendar days)` for the counters that
  grow as a drive degrades, plus how many days of history the window had;
- **context**: days in service, capacity, drive model (top 30 by *train* drives, else
  "other") and vendor, as LightGBM categoricals.

Calendar date is **not** a feature (review §4.1). Drive age comes from SMART 9
(power-on hours) and days in service.

## 6. Is it SMART that helps? The comparisons

| Model | What it is | Why it is there |
|---|---|---|
| `hazard_smart` | survival model, SMART + context | the model under test |
| `hazard_nosmart` | same model, context only | **ablation**: what you know without `smartctl` metrics. The gain over this is the answer to the project's question |
| `binary_30d` | fails-within-30-days classifier | the v2-style baseline, done correctly |
| `rule_counters` | log-sum of the reallocated / pending / uncorrectable counters | the classic rule of thumb, no training |

## 7. Evaluation (`evaluate`)

All on test drives, all weighted:

- **ROC-AUC and PR-AUC per horizon**, on snapshots whose status at the horizon is known.
  PR-AUC matters because failures are rare: a high ROC-AUC can still mean most alerts
  are false.
- **95% intervals from a drive-level bootstrap**: drives are resampled, not rows.
  Daily snapshots of one drive are nearly identical, so row-level resampling makes
  intervals far too narrow (review §4.3). The SMART-vs-no-SMART gain is bootstrapped as
  a paired difference.
- **Concordance** (Harrell's C) between predicted risk and actual time to failure.
- **Calibration**: mean predicted vs Kaplan-Meier observed failure probability per risk
  decile. Kaplan-Meier handles censored snapshots.
- **Early warning**: the threshold is set on *validation* drives for a 1% false-alarm
  rate on healthy drive-days. On test: false alarms, precision, share of failing drives
  alerted in their last 30 days, and detection by days before failure.
- **Remaining life**: for snapshots of drives that fail within a year, how often the
  predicted median falls within a year, its error, and whether the actual failure day is
  inside the predicted 10-90% interval.

## 8. The verification gate (`verify`)

Runs before any training and stops the pipeline on any error. It recomputes every
label from the cohort independently (both directions: no failure inside the window
labelled healthy, no healthy row labelled failing), and checks drive and time
disjointness of the splits, weights against the sampling config, the stable-bucket
split, no snapshot after a failure, the column schema, leak columns, feature fill, and
that the model categories come from train drives only. The report is
`build/verify-report.json`.

## 9. Limits

- **Survivor population.** Backblaze retires drives without failing them (censoring). If
  retirement is related to health, failure risk is underestimated. This can't be
  checked from the data.
- **The 365-day horizon** is only measurable on test snapshots with a year of follow-up
  (2024 snapshots). Beyond a year the model says "more than a year" and nothing more.
- **SMART semantics vary by vendor and model.** The model learns them per model where it
  has enough drives. Rare models fall into "other".
- **Results are for Backblaze's data-centre workload.** A desktop drive's environment
  differs.

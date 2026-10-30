# DeepSeek V4.1 Flash review — hard-drive-analysis-v3

- **Date:** 2026-10-26
- **Commit:** `398f421` (working tree clean except untracked `AGENTS.md`,
  `CLAUDE.md`, `article/`, `audit/`, `reports/`, `research_notes/`)
- **Scope:** `steps/`, `tests/`, `config/`, `pipeline.toml`, `docs/`, `README.md`, and both
  artifact trees (`build/` medium run, `build-arch/` full run). `../data-pipeline` was not
  read.
- **Method:** read every step module and test, then measured the questions below against
  `build-arch/` and the extracted panel, calling the project's own `metrics`, `survival`,
  `predict` and `model` functions where possible. Commands are listed in section 7. No
  project file was changed.

This review does not repeat `flint-review.md`, `gwen-3-8-review.md`,
`researcher-opus-review.md` or `glm-4-7-flash-review.md`. Section 6 maps my findings onto
theirs.

## 1. Verdict

The statistics are sound. Survival labels, censoring, splits, weights, the drive-level
bootstrap and the verification gate all hold up when checked from outside, and every
headline number in the README reproduces exactly from `build-arch/metrics.json`. 34 tests
pass in 37 s.

The weaknesses are in what the numbers are said to mean, not in how they are computed.
Four of the seven findings below are reporting or comparison defects that the pipeline
could fix without touching the model.

| # | Finding | Severity |
|---|---|---|
| W1 | Headline discrimination is drive-day weighted; the drive-level numbers are lower and the report has none | Medium |
| W2 | 2024 is already significantly miscalibrated; "inside the validation range" understates it, and the range itself has ±0.2 uncertainty | Medium |
| W3 | Concordance compares different risk functionals across models and moves by 0.2 depending on the functional | Medium |
| W4 | The binary-vs-hazard claim uses overlapping per-model intervals while the pipeline already computes the paired difference, which is negative in 97% of rounds | Medium |
| W5 | `report._timing_verdict` normalises the 10% quantile on a 0.9 scale | Low |
| W6 | Alert precision silently drops alerts whose outcome is unknown at the horizon (6.6% of alert weight) | Low |
| W7 | Gate gaps: no cohort→snapshot check, no realised-density check, no future-invariance check | Low |

## 2. What was done right

**The survival construction is correct.** I re-derived `expand`, `known_status`,
`life_quantile`, `restricted_mean_life` and `km_failure` by hand against
`tests/test_survival.py` and `tests/test_metrics.py`, including the actuarial exposure for
a snapshot censored inside a bin (`steps/survival.py:39`) and the "fails on a day < H"
convention that makes `known_status(d=H-1, censored) = 0` correct. Weights, ties and the
Fenwick-tree concordance match brute force and sklearn.

**The weights describe the sample that was actually drawn.** For every cohort drive I
compared `sum(weight) / (drive_weight × rows in the panel)` (section 7, check 5). The
median is 1.00 for train, val and test, the 99th percentile is 1.08, and reporting is
daily for 57,233 of the 57,309 cohort drives, so the stride design and the
"weight = stride" convention agree with reality. Five train drives sit at exactly 7×
(sparse reporters), which is a variance problem at most.

**The label rule has one edge case and it is harmless.** `censor_date` is
`least(last_date, train_end)` (`steps/panel.py:183`), which asserts a drive is alive
through the cutoff even if it vanished earlier and came back later. Sixteen drives (15
train, 1 val) are in that position, worth 4,230 invented drive-days out of 58.7 M. Not
worth code. This is a different set of 16 from the cohort drives that never appear in a
snapshot (W7).

**The gate bites, and it is the right shape.** 26 checks, warnings separated from errors,
labels recomputed both ways, drive and time disjointness, schema frozen,
`model_levels_from_train_only`. The tamper tests are the part most projects skip.

**The alert budget is not threshold noise, which I expected it to be.** The 1% budget is
estimated from 1.01 M validation drive-days known healthy at 30 days, but only 5,882
drives. I re-drew the validation drives 300 times, re-picked the threshold each time, and
recomputed the test false-alarm rate: 1.49% to 1.83%, mean 1.63%, matching the reported
1.63%. The gap over budget is real miscalibration, not a wobbly quantile (section 7,
check 3).

**The validation years are not flattered by in-sample calibration.** I suspected that
using validation drives as the "no drift" baseline was optimistic, since the per-bin Platt
fit is fitted on those same rows. It is not: refitting the calibration on half the
validation drives and applying it to the other half changes every yearly
predicted/observed ratio by at most 0.02 (section 7, check 4). That suspicion is dead, and
the drift argument survives one of the two obvious attacks on it.

**Operationally the project is in good order.** One contract TOML, one output tree,
deterministic writes, month-chunked DuckDB, a memory guard with a measured factor, and
issue entries that state the limit instead of hiding it.

## 3. What was done wrong

### W1. The headline metrics are drive-day weighted, and no drive-level number is reported

`discrimination`, `calibration` and `alerting` all run over snapshots
(`steps/evaluate.py:75`, `:188`). A drive observed for two years contributes up to 180
snapshots (test median 104), so the reported AUC is the AUC of a drive-*day*, not of a
drive. The sampling design shows up in the same rows: the weighted drive-day AUC at 30
days is 0.875 and the plain row AUC, without weights, is 0.832. The weighted number is the
correct estimator, but 0.04 of it comes from the dense-versus-stride correction, which is
worth stating. The README also mixes levels without saying so: "ROC-AUC 0.875" is
drive-day, "1,379 of 1,784 failing test drives (77%)" is drive-level.

Reducing every drive to one snapshot on the same test data (`hazard_smart`):

| horizon | all snapshots (reported) | one random snapshot per drive | first snapshot per drive |
|---|---|---|---|
| 7 d | 0.906 | 0.895 | 0.914 |
| 30 d | 0.875 | **0.849** | **0.846** |
| 365 d | 0.788 | 0.801 | 0.748 |

At 30 days the drive-level number is 0.026 lower than the headline. That is the quantity a
maintenance user cares about, and it is missing.

The same data answers a question the pipeline cannot currently ask. Scoring each drive by
its mean 2024 risk and asking which drives fail during 2025 — a separate drive set and a
later period than the training data — gives (7,661 drives at risk, 850 failures):

| model | drive-level AUC for failing in 2025 |
|---|---|
| hazard_smart, p365 | 0.764 |
| binary_30d | 0.763 |
| hazard_smart, p90 | 0.762 |
| hazard_smart, p30 | 0.758 |
| hazard_smart, p7 | 0.747 |
| rule_counters | 0.718 |
| hazard_nosmart | 0.603 |

One number per drive does not change the story, but it changes the shape of it: the
hazard model's four horizons land within 0.017 of each other at the drive level, against
0.12 across the snapshot table, which supports the project's own "the value is the curve"
line better than the snapshot table does.

*Fix:* add a drive-level table (one snapshot per drive per quarter, or a drive-level score
with a drive-level bootstrap) to `evaluate`, and label every table with its unit.

### W2. Drift starts at the train/test boundary, and the validation band is wider than stated

The README says the 2024 ratio (1.16×) is "inside that range" and 2025 (2.2×) is not. The
range comes from validation years and is treated as a null band. A drive-level bootstrap
of the yearly ratios (`hazard_smart`, 30 days, 100 rounds) gives intervals:

| year | split | ratio | 95% drive bootstrap |
|---|---|---|---|
| 2016 | val | 0.94 | [0.78, 1.17] |
| 2018 | val | 0.85 | [0.74, 1.01] |
| 2020 | val | 1.33 | [1.08, 1.74] |
| 2022 | val | 1.18 | [1.04, 1.35] |
| 2023 | val | 0.87 | [0.78, 0.97] |
| 2024 | test | **1.15** | **[1.06, 1.25]** |
| 2025 | test | **2.22** | **[1.96, 2.47]** |

Both test years exclude 1.0. 2024 is significantly miscalibrated in the same direction as
2025, roughly a year earlier than the README implies; the write-up reads as if 2024 were
fine and 2025 were the anomaly. Also, the validation band endpoints are themselves
uncertain by about ±0.2 (2020 spans 1.08-1.74), so "inside the range" is close to a
statement about noise. The honest version: the model over-predicts 30-day risk by 15% in
the first test year and by 122% in the second, while the validation years range from 0.85
to 1.33 with 95% intervals from 0.72 to 1.74. Recalibration is needed from the first year
of deployment.

Section 7, check 4 also rules out the in-sample-calibration explanation, so the drift is
in the data, not in the fit.

### W3. Concordance is computed from different functionals per model, and the functional matters

`evaluate.risk_of` (`steps/evaluate.py:60`) uses `-rmst_days` for hazard models and `p30`
for the binary model. On the same 300 k-row test sample:

| risk score | C-index |
|---|---|
| `-rmst_days` (what the report uses) | 0.7741 |
| `p30` | 0.7742 |
| `p365` | 0.7728 |
| `-q10_days` | 0.6917 |
| `-median_days` (infinite → large) | 0.5786 |

Two conclusions. First, the table compares a two-parameter curve collapsed into an area
against a single fixed-horizon probability, and the "0.780 vs 0.774" gap sits inside the
noise of that choice, which is why the choice should be uniform across models. Second, and
more interesting: **the model's remaining-life point estimate cannot rank snapshots.** 94.3%
of test snapshots get an infinite median (84% even among snapshots of drives that do
fail), so `-median_days` is a two-valued score and collapses to 0.579. The C-index of 0.774
is carried by the RMST, a bounded 365-day quantity whose differences between healthy
snapshots are tiny.

*Fix:* use `p30` for every model in the concordance table (the data is already there),
and say in the same paragraph that the median remaining life is infinite for 94% of
snapshots.

### W4. The binary-vs-hazard sentence uses the wrong interval

README point 4: "At 30 days the plain yes/no classifier ranks as well (ROC-AUC 0.879 vs
0.875, overlapping intervals; concordance 0.780 vs 0.774)." Overlapping per-model
intervals are not a test of a difference, and the pipeline already computes the right one
(`bootstrap_counts` on the same drive draws, applied to both models):

- AUC gain of `hazard_smart` over `binary_30d` at 30 days: **-0.0043 [-0.0083, +0.0003]**,
  and the reference model is not better in **97% of the 200 rounds**.
- AP gain: **+0.0090 [-0.0019, +0.0227]**.

So the defensible sentence is: at 30 days the two are statistically indistinguishable on
ranking, with the point estimate and 97% of paired rounds slightly favouring the binary
classifier; the survival model's contribution is one curve for every horizon and a
remaining-life estimate. As written, the README's reasoning is weaker than its own data.

`report._answer` (`steps/report.py:281`) never prints the binary comparison at all. Only
the nosmart and rule gains appear in the report body, so the generated report cannot
contradict a README that overstates the case.

### W5. `_timing_verdict` normalises the quantiles on inconsistent scales

`steps/report.py:268`:

```python
off.append((share - target) / max(target, 1 - target))
```

For the 10% quantile the denominator is 0.9, for the median 0.5, for the 90% quantile
0.9. A 3-point miss on the 10% target is therefore scored as a 3% error, while the same
absolute miss on the median is scored as 6%. The full-run numbers give mean -0.17 under
this formula and -0.26 under `target`, so the printed verdict ("too pessimistic") happens
to survive — but the 0.15 cut is close enough that a different run could flip the sentence
in the generated report without any change in the data.

*Fix:* divide by `target`, or drop the single verdict and print the three deviations.

### W6. Alert precision quietly drops the alerts it cannot judge

`steps/evaluate.py:203-213` builds `tp` from `status == 1` and `fp` from `status == 0`.
Alerts on snapshots whose status at the horizon is unknown (`status == -1`, all of them
censored by the end of the panel) enter neither. On the full run those are 723 alerts
carrying 6.65% of the alert weight (`hazard_smart`, 30 days). Reported precision 4.19%;
counting unknown alerts as misses, 3.91%.

That is a small effect and the convention is defensible, but it is neither stated in the
report nor visible in the table, and it is the one alert number that leans in the model's
favour.

### W7. Three things the gate cannot see

- **Cohort drives without snapshots.** 16 of 57,309 (14 train, 1 test, 1 val) appear in the
  cohort and in no snapshot, a different set from the censor edge case in section 2.
  `verify` checks snapshots→cohort (`snapshot_split_matches_cohort`,
  `steps/verify.py:73`) but not cohort→snapshots, so a drive could vanish from the study
  silently.
- **Realised sampling density.** `snapshot_weights_valid` (`steps/verify.py:127`) checks that
  each weight equals `drive_weight` or `stride × drive_weight`. A bug that sampled 1 day in 5
  while keeping the weight at 7 would pass the gate and inflate every weighted count by 40%.
  The realised check is one line: `sum(weight) / (drive_weight × rows) ≈ 1` (it is 1.00 today,
  section 7 check 5).
- **Future invariance of features.** There is a name-based leak check
  (`no_leak_columns_in_features`) and a date-keyed window test, but nothing recomputes a
  snapshot's features from a truncated panel. That is the only check that would catch a
  trend or completeness feature that quietly looks at rows after the snapshot. The current
  trend SQL is correct (`steps/panel.py:155`), so this is a maintenance guard, not a live bug.

## 4. Fine, but can improve

- **The ablation is 66 features against 4, and the 4 omit usage, not just health.** The
  gain of +0.27 AUC over `hazard_nosmart` is the project's headline answer, but the
  comparator sees only `days_in_service`, `capacity_tb`, `model_code`, `vendor_code`
  (`steps/panel.py:16`). Power-on hours (9), power cycles (12), start/stop (4), load cycles
  (193) and head-flying hours (240) are usage, not health, yet they sit in the SMART group.
  A third arm — context + usage counters, and no reallocated/pending/uncorrectable
  attributes — would separate "SMART carries information" from "more usable features carry
  information", and it costs one `pipeline.toml` step. A capacity-matched control (same
  input width, shuffled SMART columns) would close the "66 > 4" objection directly.
- **Brier is uninformative at this prevalence.** 0.00116 vs 0.00121 against a base rate of
  0.00121 means the whole comparison lives in the fourth decimal. Report a Brier skill
  score against the base-rate forecast, or drop the column.
- **`positive_drives` repeats 1,784 on every row of every horizon** in the discrimination
  table (all failing test drives are positive at every horizon). It reads as a per-horizon
  count. Either compute positives inside the known-status mask or drop the column.
- **`median_abs_error_days` has dead code.** `np.where(finite, med, 0)` (`steps/evaluate.py:270`)
  substitutes 0 for infinite medians and then masks to `fails & finite`, so the substitution
  never runs. It also silently excludes 84% of failing snapshots from the MAE, which the
  column name does not say.
- **Alert metrics have no intervals.** The same bootstrap applies (my check 3 is a working
  example). Without it, "4.2% precise" reads as tighter than it is.
- **Weights do not correct ROC-AUC for prevalence, although the README implies it.** The
  drive-level weight is constant within class (1 for failing drives, 10 for healthy), and
  AUC is invariant to class-constant rescaling: weighted and unweighted drive-level AUC
  are identical to the last digit. What the weights change is the mix inside each class,
  and there they matter a lot (0.875 weighted against 0.832 unweighted at 30 days). They
  are also what make AP, precision, base rate and calibration real-world quantities. One
  clause in METHODOLOGY §7 would stop a reviewer from reading 0.875 as
  prevalence-corrected.
- **Documentation drift.** `docs/METHODOLOGY.md` §1 says "664 drives keep reporting after a
  failure"; `build-arch/cohort-summary.json` says 561 for the cohort. Both may be right for
  different populations; say which.
- **`article/main-article.md` is still `to do`.** Per `AGENTS.md` the article is the main
  deliverable, and there are five research notes and a 34 kB methodology debate in
  `reports/` feeding it. The pipeline is finished; the write-up has not started.

## 5. Interesting details that need a deeper investigation

### D1. Performance varies by vendor more than the headline suggests

30-day snapshot AUC by vendor on the test set (`hazard_smart`), with the count of failing
test drives per vendor:

| vendor | failing drives | base rate | hazard_smart | no SMART | rule |
|---|---|---|---|---|---|
| HGST | 380 | 0.24% | **0.923** | 0.622 | 0.888 |
| Seagate | 764 | 0.14% | 0.902 | 0.609 | 0.848 |
| WDC | 155 | 0.05% | 0.824 | 0.537 | 0.785 |
| Toshiba | 485 | 0.10% | **0.783** | 0.518 | 0.740 |

`smart_187_raw`, the single strongest attribute in `build-arch/explore/feature_signal.csv`
(0.669 alone), is populated on 99.8% of Seagate snapshots and 0.0% of HGST, Toshiba and
WDC. The best-performing vendor never reports it. That rules out "the model is a 187
detector", but it also means the headline 0.875 is an average over populations that differ
by 0.14 AUC, and the vendor mix decides the number. A per-vendor table belongs next to the
headline, and the article's generalisation claim should carry it.

### D2. Retirement is partially measurable, and the answer supports the documented guess

`docs/ISSUES.md` #7 says "the data can't confirm or rule this out". It can, partly. Among
the 6,318 test drives seen in 2024 that never fail in the test period, 386 stop reporting
before 2025 and 5,932 continue. Their mean 2024 predicted 30-day risk:

| group | drives | mean 2024 p30 | median | share above 1% |
|---|---|---|---|---|
| vanish after 2024, no failure | 386 | **0.0034** | 0.00061 | 4.7% |
| continue into 2025 | 5,932 | **0.0010** | 0.00037 | 1.8% |

Drives that disappear carry 3.4× the predicted risk of drives that stay, and 2.6× the
share above a 1% alert threshold. That is evidence that Backblaze's retirement and the
model's risk score share signal, which is the mechanism issue #7 and #9 hypothesise. Note
the limits: 386 drives, low absolute risk, and the effect is far too small to explain the
2025 factor of 2.2.

### D3. "Failure" and "retirement" may be the same latent event

Following D2: if the label is an operator decision and retirement correlates with the
model's risk score, then a chunk of what the model learns is "this drive will leave the
panel", not "this drive will die". A clean experiment: retrain with the event defined as
"leaves the panel" (failure or retirement) and compare (a) AUC for the failure label and
(b) the calibration drift by year. If the drift shrinks, the model was predicting
retirement; if it does not, the 2025 gap is a real change in the fleet. Either result is
publishable, and the project already has every input it needs.

### D4. The remaining-life answer is "more than a year" for most snapshots

94.3% of test snapshots get an infinite median, and so do 84% of the snapshots of drives
that fail, among those whose 365-day status is known. The report does say 99.8% for healthy
drives, but not the overall number, and the README's phrasing ("can only be answered close
to the end", 47% in the last week, 8% at 6-12 months) leaves the impression that the model
commits more often than it does. Worth one sentence with the 84%, and worth plotting the
share of *finite* medians against lead time in `report.py` — the life table already
contains the numerator.

### D5. The survival curve is too flat, and the Platt coefficients show it

The quantile calibration runs the same way at both scales: 7% fail by the predicted 10% day,
33% by the predicted median, 76% by the predicted 90% day. All seven fitted slopes sit in
1.16-1.33 and all seven intercepts in -1.21 to +0.09, so the post-hoc fit is nearly a
single affine correction on the logit scale per bin. That is consistent with a shape error
in the curve rather than a scale error, as `glm-4-7-flash-review.md` D1 argues, and the
coefficient pattern is the evidence for it. A two-parameter joint fit (shared slope, per-bin
intercept) is a 20-line change in `survival.fit_platt` and would test the hypothesis
directly.

### D6. Test what drives the 7-day AUC besides SMART

The failure-day snapshot is in the label window by construction, and the operator likely
acted on that day's SMART values. `researcher-opus-review.md` R4 measures this (0.866 with
positives ≥ 7 days out) and R3 measures the silent-failure slice (0.627). Both numbers
should be in the generated report, not only in an audit, because they are the two limits a
reader will ask about first. Neither is a pipeline feature yet.

## 6. Relation to the earlier reviews

| Earlier finding | This review |
|---|---|
| flint §6.1 / glm W1, README paths | Not re-checked. `README.md` still points at `build/report/report.md` for full-scale numbers, which live in `build-arch/`. |
| opus R1 / glm W2, importance figure | Confirmed by reading `write_json` + alphabetical `head(20)`; not re-measured. |
| opus R2, packed SMART 188 | Not re-checked. My D1 shows the model does not need 187, which is the neighbouring question. |
| opus R3 / glm W4, label circularity | Not re-measured; my W1 drive-level table and D3 extend the same concern to a different slice. |
| opus R4, last-week positives | Not re-measured; D6 asks for it in the report. |
| opus R5, validation drives do three jobs | Confirmed. My check 4 shows the calibration reuse does not distort the yearly drift baseline, which narrows R5 to the threshold and early stopping. |
| opus R6, age vs days in panel | Confirmed. My W1/D1 are separate. |
| opus R8 / glm, alert intervals | Confirmed; my check 3 supplies the interval and rules out threshold noise as the cause of 1.63%. |
| opus R7, horizons drop censored rows | Confirmed; nothing new. |
| glm D1, flat curve | Confirmed with the Platt coefficient pattern (D5). |
| glm D2, 2025 drift mechanism | Advanced: D2 gives the retirement measurement, W2 gives the yearly intervals. |
| glm D4, context-only model near chance | Confirmed at the drive level too (0.603 for failing in 2025). |
| glm 4, ideas list | Overlaps my section 4. |

None of the seven findings above is in the four earlier reviews. W1, W2, W3, W4 and W6 are
new measurements; W5 and W7 are new code readings.

## 7. Checks performed for this review

All run from the repository root with `.venv/bin/python`; nothing was written except this
file.

1. **Reproduce the headline.** Recomputed from `build-arch/metrics.json`: 7-day AUC 0.9057,
   SMART gain +0.3004 [0.287, 0.3146], alerting 1,379/1,784 at 4.19% precision and 1.63%
   false-alarm rate, quantile calibration 7.1/33.5/76.1%, medium-scale 365-day AUC 0.733
   against 0.788 at full scale. All match the README.
2. **Drive-day vs drive-level AUC** (W1). One random and one first snapshot per drive, on
   the known-status mask, using `metrics.weighted_auc`; also the same rows with all weights
   set to 1 (0.832 against 0.875 at 30 days).
3. **Alert threshold stability** (W6, section 2). 300 drive-level resamples of the
   validation healthy drive-days, re-picking the threshold with
   `metrics.weighted_quantile_threshold` and recomputing the test false-alarm rate and
   precision: FAR 1.49-1.83%, precision 3.83-4.49%.
4. **In-sample calibration check** (W2). Recomputed the model's raw logits for all 1.08 M
   validation snapshots with `model.raw_hazard_logits`, refitted the seven per-bin Platt
   pairs with `survival.fit_platt` on a stable-hash half of the validation drives, and
   applied them to the other half. Yearly predicted/observed ratios move by at most 0.02
   against the stored calibration.
5. **Weight design vs the drawn sample** (section 2, W7). `sum(weight) / (drive_weight ×
   panel rows)` per drive from `build-arch/panel` and `build-arch/cohort.parquet`: median
   1.00, p99 1.08, 5 train drives at 7×, 116 test drives below 0.5 (the pre-`test_start`
   load window, expected).
6. **Label censor edge case** (section 2). 16 drives have a reporting gap across
   `train_end`, worth 4,230 invented drive-days.
7. **Cohort vs snapshots** (W7). 16 cohort drives have no snapshot.
8. **Concordance sensitivity** (W3). Same 300 k sample; hazard, binary and rule scores
   collapsed five different ways.
9. **Per-year calibration with intervals** (W2). 100 drive-level bootstrap rounds over
   val+test, weighted KM per year.
10. **Vendor breakdown** (D1). Test snapshots merged with cohort vendor; AUC per vendor;
    `smart_187_raw` fill rate per vendor.
11. **Retirement** (D2). Test drives with 2024 snapshots, split by presence in 2025.
12. **Out-of-time drive-level AUC** (W1). 2024 mean score against "fails during 2025", 7,661
    drives at risk, 850 failures.
13. **Test suite.** `uv run pytest -q` → 34 passed in 36.7 s.

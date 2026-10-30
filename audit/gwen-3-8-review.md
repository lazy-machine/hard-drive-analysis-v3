# Project review — hard-drive-analysis-v3

Reviewed: full repository at commit `6027a87` (+ the untracked local `build/`, `build-arch/`,
`dataset/`), code read end-to-end (`steps/`, `tests/`, `config/`, `pipeline.toml`, docs),
test suite executed, and README claims cross-checked against the full-scale artifacts in
`build-arch/`. This article says what was done right, what was done wrong, and how to
improve the project.

## 1. What the project is

Can `smartctl` SMART readings from a running drive predict *how likely* it is to fail and
*roughly when*? The pipeline answers it on Backblaze's 2016–2025 drive panel
(646.8M drive-day rows, 478k drives, 26.7k failures):

```
dataset.parquet → drive_index → extract → cohort → snapshots
  → verify (gate, halts on error) → train_{hazard_smart,hazard_nosmart,binary_30d}
  → predict → evaluate → report
```

The model is a discrete-time hazard (LightGBM over 7 risk bins per drive-day, with a
bin-start feature), censored at the observation boundary, trained on tempered
inverse-probability weights (`weight_power = 0.5`) and recalibrated per bin on validation
drives. Four models are compared — SMART + context, context-only (the ablation that
answers the question), a v2-style 30-day binary classifier, and a no-training rule on the
failure counters.

**Result (verified against `build-arch/metrics.json`):** at full scale (57,309 cohort
drives, 8,981 test drives, 1,784 failures) the SMART hazard model has 30-day ROC-AUC
0.875 [0.867, 0.884] and PR-AUC 12.7% vs 0.1% base rate; over the context-only model the
AUC gain is +0.273 at 30 days (CI [0.259, 0.288], 0/200 bootstrap rounds without a gain);
it beats the simple rule by +0.056 at 7 days; the no-SMART model is near chance
(0.602 at 30 days). At a 1% false-alarm budget (set on validation), 1,379/1,784 (77%) of
failing test drives were flagged in their last 30 days at 4.2% precision. 34% of
pre-failure snapshots were failed by their *predicted* median remaining life. All README
numbers checked: they match the artifacts exactly.

## 2. What was done right

**2.1 The question was posed as a survival problem, and the censored boundary is handled correctly.**
The worst v2 bug was labelling drives that failed *after* the training cutoff as healthy.
v3 censors them (`event = 0`, duration to `train_end`), and the one remaining subtlety — a
snapshot censored *inside* a risk bin — is handled by fractional exposure (`duration −
bin_start` within the bin, `steps/survival.py:expand`). That single decision makes the
whole analysis statistically honest. `steps/survival.py:km_failure` shows the care: the
KM at-risk set is computed as "total weight minus weight with duration < day", which is
the correct convention for "alive through day t".

**2.2 The ablation design directly answers the research question.**
`hazard_nosmart` isolates "what you know without `smartctl`", `rule_counters` is the
classic no-training baseline, and `binary_30d` is the v2-style question done correctly.
Because all four share the same snapshot/weight machinery, the paired drive-level
bootstrap gain (`evaluate.reference_gain`) is a clean, interval-bearing answer: *yes,
SMART adds ~0.27 AUC at 30 days, and the simple rule captures most of the near-term
signal — the model's edge is the longer horizons and the risk magnitudes.*

**2.3 Weights are end-to-end consistent.**
Stratified drive sampling (20% failing / 2% healthy) is inverted into per-snapshot
weights, every reported metric is weighted, and the gate re-derives every weight from the
sampling config (`verify.cohort_weights_match_sampling`, `snapshot_weights_valid`). The
tempering (`weight_power = 0.5`) is a *deliberate, documented* distortion — full weights
starve training (ISSUES #8) — and it is compensated by per-bin Platt recalibration on
validation drives with the *true* weights (`steps/model.py:calibrate`). The report's
probabilities are therefore on the real-world scale (base rate 0.027% at 7 days), not the
enriched sample's. This chain — sample → weight → temper → recalibrate — is the sort of
thing most applied projects get wrong; here each link is implemented, documented, and
partially gated.

**2.4 The verification gate is a real gate.**
`verify` runs before any training and recomputes labels independently of the snapshot
code (both directions: no visible failure labelled censored, no healthy row labelled
failing), checks drive-time disjointness of splits, no snapshot after a failure, leak
columns against a schema, and that model categories come from train drives only. 26/26
checks pass at full scale (`build-arch/verify-report.json`). Crucially, the test suite
*injects* the v2 label bug and asserts the gate catches it (`test_gate_catches_v2_label_bug`)
— the gate's power is evidence, not faith.

**2.5 The test suite is unusually good for this genre.**
34 tests, ~40 s, all passing. The synthetic panel (`tests/synth.py`) reproduces the
real data's quirks with known answers: boot-SSD exclusion, same-day duplicates, drives
reporting after failure, two failure rows, VARCHAR SMART columns, whitespace-in-model-name.
Metric code is unit-tested against `sklearn` and brute force (tie handling, weighted
quantiles, cluster bootstrap resampling whole drives, KM). There is an end-to-end run and
tamper tests. `test_gate_catches_v2_label_bug` and
`test_train_failure_after_cutoff_is_censored_not_negative` pin the two historically
dangerous decisions in code.

**2.6 The engineering is disciplined.**
- One contract file (`config/study.toml`) that every step and the gate read — no copied
  constants (the v2 sin of hand-copied contract constants is gone).
- Deterministic everything: `sha256` stable-bucket splits (not DuckDB's hash, which
  changes between versions), ordered output, seeded RNGs, deterministic LightGBM,
  content-hash checkpoints with cascade invalidation.
- Memory-aware by construction: month-chunked panel processing, drive-batched feature
  extraction, the survival expansion streamed as a sequence (never materialised), and a
  hard memory guard that refuses a training run whose estimate exceeds 90% of available
  RAM (`steps/model.py:_check_memory`). On a 31 GB box the full 650M-row panel runs in
  30 minutes (ISSUES #1 has the per-step timings).
- `pipeline.toml` is the single source of truth for steps and models; `predict` discovers
  models from its inputs rather than a hand-maintained list.

**2.7 The reporting is honest and generated, not hand-written.**
`report.py` turns `metrics.json` into prose, and the "Answer" sentences are *derived from
the numbers* (a conclusion only appears when its CI excludes zero). Limits are stated in
the methodology and the issue log: the 365-day horizon is only measurable on 2024 test
snapshots, retirement censoring may be informative, drift is open, results are
data-centre specific. `docs/REVIEW-RESOLUTION.md` maps every v2 review finding to its v3
resolution and its guarding test. That document is a model of how to close out a review.

## 3. What was done wrong (or left undone)

Nothing here is a bug in the results — the numbers reproduce and the gate and tests hold.
The problems are gaps, ranked by how much they matter.

**3.1 The headline results are not reproducible from the repository.** *(biggest gap)*
`build/` and `build-arch/` are gitignored. The README's full-scale numbers come from a run
on a 31 GB machine whose artifacts exist only on this machine. A fresh checkout cannot
reproduce the published results end-to-end because:
- the full-scale `metrics.json` / `report.md` / `verify-report.json` are not committed
  (they are small JSON/MD files — committing them would cost nothing);
- the 22 GB `dataset/dataset.parquet` has no provenance pin (no content hash, no fetch
  manifest); Backblaze's panel is a living dataset, so a re-download could silently
  change the data under a stable commit;
- the orchestrator is an *editable path dependency* on a sibling repo
  (`data-pipeline = { path = "../data-pipeline", editable = true }` in `pyproject.toml`),
  which a fresh clone does not have.
- Related: the project declares a console script `hda = data_pipeline.cli:main` but
  `uv run hda` fails ("No such file or directory") in the provided environment — the
  declared entry point is dead; only `uv run data-pipeline` works.

**3.2 Temporal drift is open and the model is used past its calibrated range.**
ISSUES #9 is honest about it, but the pipeline still reports test-year numbers as if the
calibration held. Full scale: predicted vs observed 30-day risk is 1.16× in 2024 (inside
the validation-year range of 0.85–1.32×) and **2.2× in 2025**, well outside it. The
consequence is visible in the alerting numbers: the 1% false-alarm budget becomes
1.6%–1.9% on test. The README says "recalibrate before production use" but the pipeline
has no recalibration step and no drift gate: a run in 2026 would ship the same stale
calibration with no warning that the 2025 gap widened. The suggested fix (recalibrate on
the most recent pre-test year, or a rolling-origin evaluation) is written down and never
implemented.

**3.3 Retirement censoring is assumed non-informative — untestable, and the drift may be
its fingerprint.**
Backblaze retires drives without failure rows; if retirement is health-driven, failures
are undercounted and all reported risks are *underestimates*. The methodology says so.
But the issue log connects it to #9 (later-year observed risk falling below trained
expectations) and does nothing to quantify it. There is no sensitivity analysis bounding
the bias (e.g., re-weighting the censored population, or comparing the failure rate of
drives that leave the panel vs. those that stay). For a project whose stated goal is
"how likely is this drive to fail", this is the largest validity threat and it gets only
one paragraph.

**3.4 The training-weight exponent is a heuristic with one data point.**
`weight_power = 0.5` was chosen because it beat 1.0 on validation AUC (ISSUES #8).
Nothing searches or brackets it: 0.5 vs 1.0 is a two-point comparison, no sensitivity of
the final numbers to the exponent is reported, and the docs themselves warn "if you change
the sampling fractions, recheck `weight_power` there". The per-bin Platt fit is what makes
the probabilities usable, but its assumptions are not stress-tested: each bin is
calibrated independently on validation data, and the long bins (180–365 days) have few
validation failures, so those coefficients are the noisiest — exactly where the survival
curve's tail is decided. There is no test or report line showing the recalibrated
curves remain sensible bin by bin beyond the top-decile number quoted in the methodology.

**3.5 The concordance risk score conflates "how likely" with "when".**
For hazard models, `evaluate.concordance` ranks by `−rmst_days` (negative expected days
alive within a year). RMST is a *time* measure: two drives can share an RMST while having
opposite hazard shapes (imminent small risk vs. steady larger risk). Since every healthy
drive has RMST ≈ 365, the score's discriminative power comes almost entirely from the
failing drives' shortened tails. A level-based score (e.g. `1 − S(365)` or the integrated
hazard) would be available from the same predictions at no cost and would be a fairer
"risk" for a concordance. As built, the concordance (0.774) quietly under-reports the
model's risk ranking.

**3.6 Cross-horizon AUCs compare subtly different populations.**
AUC at horizon H is computed on snapshots with *known* status at H. For H = 365 that is
only 2024 test snapshots (a year of follow-up is needed; ISSUES #6); for H = 7 it is
2024–2025. The horizons are therefore measured on different calendar cohorts with
different failure climates (the drift makes this non-trivial). The report shows the
AUCs side by side without flagging that the 365-day number comes from a strictly
earlier, higher-failure-rate cohort. A one-line caveat in `report.py` would fix it.

**3.7 Trend features use the *earliest* value in the window, which goes stale under gaps.**
`first_value(...) IGNORE NULLS OVER RANGE 30 DAY` means "change over the last 30 days" is
actually "change since the oldest reading available in the window". A drive that was
silent for 25 of those 30 days gets a trend spanning however long its real gap was. The
`window_days_*` features partially compensate (the model can see the gap), but the
cleaner feature is the value at the *window start* (or the least-squares slope). This
matters because the trends are among the strongest signals in a dataset of daily
snapshots.

**3.8 Smaller issues.**
- **No CI, no linter, no type checker.** A ~2,600-line statistical codebase with 34 tests
  runs only locally; nothing prevents a broken commit from landing. `scikit-learn` is a
  runtime dependency used exclusively by tests (should be a dev dependency).
- **No LICENSE file** in a repo that documents itself as a successor project.
- **`article/research/` is an empty directory** — a leftover.
- **No test for the memory guard** (`_check_memory`), the one safety mechanism that can
  silently shrink a run's scope; a unit test with a fake psutil figure would close it.
- **Dense pre-failure coverage is trimmed for early test failures.** `snapshots` restricts
  test drives to `date >= test_start`, so a drive failing in Jan 2024 loses its Nov–Dec
  2023 dense snapshots even though `extract` kept them. Not a leak, but the "run-up to
  failure is seen in full detail" claim is true only inside the test window.
- **Alerting mixes units.** `precision_test` and `recall_snapshots_test` are snapshot-day
  quantities while `failing_drives_alerted` is drive-level; the report presents them
  together and the reader has to hold both units in head. A small table fix, not a
  correctness issue.
- **The `verify` "enough failures" warning threshold (< 30) is an unexplained magic
  number** — fine as a warning, but it deserves a comment or config entry.

## 4. How to improve the project

Prioritized; each item is concrete and small enough to be a standalone change.

**P1 — Make the headline reproducible from the repo.**
- Commit the full-scale small artifacts: `metrics.json`, `report.md`, `verify-report.json`
  (and the four model `.txt` + `.json` pairs, ~100 KB total) to a `results/full/` directory
  in git, produced by the exact `sample.toml` they ran under.
- Record dataset provenance in the repo: fetch URL/date and the `sha256` of
  `dataset.parquet` (one line in `cohort-summary.json` or a `DATASET.md`); have `drive_index`
  assert it on load.
- Either vendor `data-pipeline` into this repo (it is the only orchestrator the project
  needs) or publish it as a package with a version pin; an editable sibling path is not a
  dependency spec. Fix or drop the dead `hda` entry point.

**P2 — Close the drift loop, not just document it.**
- Add a pipeline step (or a `verify`-level check in the report) that compares predicted vs
  observed risk per pre-test year on *validation-era* data and fails loudly when the
  latest pre-test year is outside the range of earlier years — i.e., detect #9 *before*
  the test numbers are trusted.
- Implement the recalibration already suggested in ISSUES #9: refit the per-bin Platt
  coefficients on the most recent pre-test year (the machinery exists in
  `model.py:calibrate`; this is a scope change, not new code), and report both the old and
  new 2025 calibration so the effect is visible.
- Add a rolling-origin evaluation (train ≤ 2022, test 2023; train ≤ 2023, test 2024; …)
  as the honest way to state "does the model age well?".

**P3 — Bound the two untestable assumptions.**
- Weight-power sensitivity: train at `weight_power ∈ {0.5, 0.75, 1.0}` (with recalibration
  in each case), report the 30-day AUC and the top-decile calibration as a small table.
  This converts "0.5 works" from assertion to evidence and tells you how fragile the
  result is to the sampling fractions.
- Informative-censoring sensitivity: a simple, cheap version is to compare the observed
  failure rate of drives that *stop reporting* (censored) vs. drives that keep reporting,
  by year and by final counter levels; if censored drives look healthier, the downward
  bias is small. Even a paragraph of this in the report would upgrade the retirement
  limit from assumption to measurement.

**P4 — Fix the two metric weaknesses that are cheap to fix.**
- Concordance: rank hazard models by `1 − S(365)` (already in the predictions) instead of
  `−rmst`; report both for transparency.
- Trend features: replace `first_value` with the value at the window start (a
  `RANGE BETWEEN ... PRECEDING` lookback, or `LAG`-free `first_value` over a *preceding-only*
  window), keeping `window_days_*`. Re-run; if AUC moves, the old feature was quietly
  doing gap-correction work.

**P5 — Tooling hygiene.**
- CI: run `uv run pytest` on push (the suite is 40 s — there is no excuse for it not to run
  in CI); add `ruff` (the code is already clean) and a type checker if desired.
- Move `scikit-learn` to a dev dependency; add a `LICENSE`; delete the empty
  `article/research/` tree or give it a purpose.
- Unit-test `_check_memory` (fake available memory → guard trips) so the memory behaviour
  is pinned like everything else.

**P6 — Reporting polish (cosmetic but it changes how the results land).**
- State in the report that the 365-day AUC comes from 2024-only snapshots.
- Present the alerting table with its units labelled (snapshot-day precision vs
  drive-level alert share) and put the 1%→1.6–1.9% budget breach next to the drift
  paragraph instead of only in the issue log.
- In the life section, note explicitly that the "47% in the last week / 8% at 6–12
  months" numbers are shares *of failing drives' snapshots* — the single most quotable
  number in the project, so it should carry its own conditions on the same page.

## 5. Bottom line

This is a rare, high-quality applied-statistics project: the v2 review's fatal errors
(label boundary, leaky splits, row-level inference, sample-dependent features) were fixed
at the root rather than patched, and the fixes are guarded by a gate and a test suite that
deliberately re-inject the old bugs. The statistics — censoring, weighting, cluster
bootstrap, per-bin recalibration — are implemented correctly and the reported results are
reproducible from the local artifacts (verified: all README numbers match
`build-arch/metrics.json`; gate 26/26; 34/34 tests pass in ~40 s).

The project's remaining risk is not in the code but in its *validity envelope*: drift is
measured but uncorrected and ungated, retirement censoring is assumed rather than
bounded, the weight exponent is a two-point heuristic, and the headline results live
outside the repository. None of the P1–P3 items above requires new machinery — they
require committing small artifacts, one new step that reuses `calibrate`, and two
sensitivity runs. Closing those would move this from "careful analysis with an open
drift flag" to "analysis whose stated limits are measured limits".

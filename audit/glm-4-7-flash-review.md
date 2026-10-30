# GLM-4.7-Flash review — hard-drive-analysis-v3

- **Date:** 2026-10-25
- **Commit:** `398f421` (working tree has untracked docs: `AGENTS.md`, `article/`,
  `audit/`, `reports/`, `research_notes/`)
- **Scope:** `steps/`, `tests/`, `pipeline.toml`, `config/`, docs, and both artifact
  trees (`build/` medium run, `build-arch/` full run). The orchestrator
  (`../data-pipeline`) was not read. Dataset/dataset.parquet queried directly for two
  checks.
- **Method:** read every step module and test, ran the test suite, re-derived the
  headline numbers from `build-arch/metrics.json`, and ran independent DuckDB/numpy
  checks against the artifacts and the raw panel. Where a finding repeats an earlier
  review it says so and adds only the new evidence.

This review is organized around four questions: what was done right, what was done
wrong, what is fine but can improve, and what deserves deeper investigation. Section 6
cross-references the three earlier reviews so the four lists stay honest.

## 1. Verdict

The methodology is sound and the code is honest about its limits. Every headline number
in the README reproduces exactly from `build-arch/metrics.json`; the survival labels,
the drive-and-time split, the inverse-probability weights and the weighted metrics are
all correct, and 34 tests pass. The weakest part of the project is not the statistics —
it is the gap between what the pipeline computes and what the Backblaze label actually
means, plus a handful of reporting defects that misstate the results.

The three earlier reviews (flint, gwen-3-8, researcher-opus) are accurate. Of their
findings, at least one High item (the README pointing at the wrong run) remains unfixed
at `398f421`.

## 2. What was done right

**The survival math is correct and independently testable.** `survival.expand` builds
person-period rows with actuarial exposure for snapshots censored inside a bin;
`known_status` treats "fails within H days" as failure on a day < H, and censors a drive
alive through day H-1 correctly. I traced both conventions against the hand-computed
tests in `tests/test_survival.py` and they agree.

**The verification gate actually bites.** `steps/verify.py` recomputes labels from the
cohort in both directions, checks split integrity, weights, schema and leak columns,
and fails the pipeline before training. The gate tests in
`tests/test_cohort_and_gate.py` inject known v2 bugs and prove the gate catches them.
At full scale it passes 26/26.

**The headline numbers reproduce.** I re-derived every row of the README's AUC table
from `build-arch/metrics.json`: 7-day 0.906 vs 0.605 (no-SMART), 30-day 0.875 vs 0.602,
gains +0.300/+0.273 with CIs matching to three decimals. The alerting row (1,379/1,784
failing test drives, 4.2% precision) and the life numbers (34% failed by predicted
median against a 50% target) also match.

**Drift is surfaced, not buried.** The calibration-over-time table puts predicted vs
observed risk per year in the report, and the README states the 2025 ratio of 2.2x
plainly. A weaker project would have printed a single aggregate calibration number and
called it a day.

**The report is generated, not written.** Conclusions in `build/report/report.md` are
derived from the metrics (claims about SMART's value are gated on the bootstrap CI
excluding zero). The report cannot drift from the results the way v2's did.

**The 2025 test protocol is genuinely held out.** Test drives are never scored before
2024, the alert threshold is set on validation drives, and no test row influences
model selection or calibration. I checked the gate's split-disjointness and
no-train-row-after-cutoff checks directly.

## 3. What was done wrong

Findings in decreasing severity. The first three were raised by researcher-opus; I
re-derived each independently and the evidence below is mine.

### W1. The README points at the wrong run (High, still unfixed)

`README.md` line 17: "The full tables are in `build/report/report.md`." That file is
the **medium** run's report (scale: medium, 11,575 cohort drives, 359 failing test
drives — `build/cohort-summary.json`). The full-scale tables the README summarizes live
in `build-arch/report/report.md`. A reader following the pointer gets numbers that do
not match the ones on the page. Flint flagged this; commit `edfa60d` did not fix it.

### W2. The importance figure shows the wrong features (High)

`report.py` does `pd.Series(meta_ref["importance_gain"]).head(20)`, expecting the dict
to be ordered by gain. But `common.write_json` serializes with `sort_keys=True`, so by
the time the dict reaches `report.py` its keys are alphabetical. The figure's "top 20"
is the first 20 features by name: in `build/models/hazard_smart.json` the alphabetical
head is `bin_start, capacity_tb, days_in_service, model_code, smart_10_raw` — while the
actual top five by gain are `bin_start, smart_197_raw, capacity_tb, smart_187_raw,
model_code`. `smart_197_raw` (pending sectors) drops out of the figure entirely.
Fix: sort in `report.py` (the metadata dict should also stay gain-sorted in memory).

### W3. The classic-rule baseline is handicapped by vendor packing (High)

`predict.rule_score` sums `log1p` of the five critical counters' **raw** values. Seagate
packs `smart_188_raw` (command timeout) with non-counter semantics: in one month of the
2025 panel I measured mean 1.09e9 and max 2.2e12 across 3.3M Seagate rows, while WDC
reports plain counts (mean ~0, max 96) and Toshiba/HGST report 188 not at all. A Seagate
drive-day therefore scores enormously on a counter that does not mean what the rule
thinks, and the rule's alert budget is spent on Seagate noise. This is the strongest
single reason the model's lead over the rule (77% vs 66% of failing drives flagged at
full scale) understates the model's real advantage. Fix: either drop 188 from
`critical_counters`, or compute the rule per vendor with a per-model normalization.

### W4. Label circularity is known but never measured by the pipeline (High)

Backblaze schedules replacement "once SMART 187 goes above zero" and counts proactive
removals as failures (see `reports/SMART failure prediction methodology debate.md`), so
part of what the model learns is the operator's own policy. My clean-label slice: among
test drives that **never** show any of the five critical counters anywhere in their test
window (6,945 of 8,981 drives; 349 of 1,784 failing ones), the SMART model's 30-day AUC
is **0.660** over 570,610 known-status snapshots, against 0.835 on drives that do show a
counter and 0.875 overall. Researcher-opus got 0.627 on a differently-defined slice.
Both say the same thing: roughly a third of the model's discrimination evaporates when
the counters that define the label are absent. The pipeline computes this in nothing —
it belongs in `evaluate` as a permanent slice, because every future run will have the
same blind spot and no reviewer.

### W5. `scipy` is used but not declared (Medium)

`survival.fit_platt` imports `scipy.optimize`, but `pyproject.toml` declares only
duckdb, lightgbm, matplotlib, numpy, pandas, pyarrow, scikit-learn. It works today
because scikit-learn pulls scipy transitively; a dependency change breaks calibration
at runtime, and on a fresh `uv sync` the import could fail after training has already
spent 10 minutes. One line fixes it.

### W6. The failure-day snapshot is scored like any other (Medium)

The panel's failure row carries the last scan's SMART values, and `panel.snapshots`
includes the failure day (duration 0, dense window). In my January-2025 sample, 377 of
377 failure rows have `smart_5_raw` populated and 24% show growth over the previous
day. So the evaluation scores a drive **on the day it dies**, using values that either
precede the death by minutes or are the last scan before it. A deployed system would
never see that day's data. The last-7-days snapshot block (which is almost all duration
0-6) has 30-day AP = 1.0 in my check — a perfect ranking no deployment can achieve. The
headline "77% of failing drives were flagged in their last 30 days" and the PR-AUCs
inherit this. The fix is cheap: exclude duration-0 snapshots (or all snapshots within
one reporting day of the failure) from the precision/recall metrics and restate the
headline. Researcher-opus found the neighboring effect (R4) by dropping the last week;
the duration-0 row is the cleaner cut and nobody has quantified it.

## 4. Fine, but can improve

These are correct as built; each is a small step up.

- **Bootstrap intervals.** The drive-level percentile bootstrap (200 rounds) is right
  for clustered data, but resampling drives uniformly ignores the stratified sampling
  (failing drives kept at 100%, healthy at 10%). A stratum-preserving bootstrap would
  be slightly more faithful; with 1,784 failing test drives the difference is likely
  small, but it is free to add.
- **Alert metrics have no intervals.** Precision, recall and the per-drive detection
  rates are point estimates while AUCs carry CIs. The same bootstrap machinery applies;
  `alerting` just doesn't use it (researcher-opus R8).
- **Concordance subsamples rows.** `evaluate` caps the C-index computation at 300k
  rows via `test.sample(...)`. Row-level subsampling is unbiased, but it breaks the
  drive-cluster logic used everywhere else; sampling whole drives would be consistent.
- **`days_in_service` is not true age.** It counts days since the drive's first row in
  the panel. Drives already in service in 2016 start the panel with an understated age,
  and the no-SMART ablation — the model against which SMART's value is measured —
  cannot recover the true age from `days_in_service` or SMART 9 alone (researcher-opus
  R6 covers the model-side effect; the documentation side is mine: the feature's name
  and METHODOLOGY §5 should say "days observed in panel").
- **Tie handling at the alert threshold.** `weighted_quantile_threshold` picks the
  smallest threshold whose tie-group-inclusive weighted share fits the budget. That is
  conservative and correct, but when the threshold lands on a large tie group the
  realized FAR can be well under 1%. Reporting the realized FAR alongside the budget
  (it does) is enough; a sentence in the docs would help future readers.
- **The article does not exist yet.** `article/main-article.md` contains the string
  "to do". Five research notes and the methodology-debate report exist; the study
  itself — the project's stated purpose per AGENTS.md — has not been started.

## 5. Interesting details that need deeper investigation

### D1. The survival curve is systematically too flat — and per-bin Platt won't fix it

Across both scales the quantile calibration runs the same direction: 6-7% of drives
failed by the predicted 10% day (target 10%), 30-34% by the predicted median (target
50%), 76-88% by the predicted 90% day (target 90%). The curve is consistently too
optimistic — more slowly decaying than reality. Platt recalibration fits each hazard
bin's marginal scale independently; it cannot fix a *shape* error, which is what this
pattern is. Worth an experiment: fit the bin coefficients jointly (or add a shared
slope across bins) on validation drives and check whether the quantile targets close.
The README's point 3 ("too pessimistic on the test years") is this same effect seen
from the other side, and the current writeup does not connect the two.

### D2. Drift in 2025 is an open mechanism question

Validation years wander between 0.85x and 1.32x with no trend; test 2024 is 1.16x,
test 2025 is 2.2x. Two candidate mechanisms (ISSUES #7 and #9): Backblaze retiring
risky drives before they fail, or the fleet's composition changing. The data can
partially separate them: if retirement is the cause, the *healthy* drives' observed
failure rate should drop most where retirement concentrated, and the no-SMART model
(which only knows model/capacity/age) should drift differently from the SMART model.
Neither check exists. A rolling-origin evaluation would also answer whether the 2025
gap is permanent or would shrink with a one-year lag.

### D3. Vendor semantics are a structural feature of the panel, not a one-off

The 188 packing (W3) generalizes: SMART raw meanings differ by vendor and even by
model family (the ktz-2024 reference in `article/research/` documents several). The
pipeline handles this only by giving the model the raw column and letting it learn.
Two cheap, testable follow-ups: (a) a per-vendor transform for the known-packed
attributes, (b) checking whether the model's per-model splits in LightGBM recover the
packing automatically. Either would move the debate about "does the model understand
the counters" from anecdote to measurement.

### D4. The context-only model is near chance, which is itself a result

`hazard_nosmart` sits at 0.595-0.605 AUC at every horizon. Capacity, model and
time-in-service — the features published studies lean on for fleet-level claims — carry
almost nothing at the individual-drive level in this panel. That is a substantive
finding for the article (it contradicts several of the references in
`article/research/`), and the mechanism deserves a paragraph: the panel's fleet
composition may make model-level failure rates useless conditional on age, or the
censoring of pre-2016 history (D1 of researcher-opus R6) may be hiding real age signal.

### D5. Does the SMART gain survive on the clean-label slice at longer horizons?

The circularity slice (W4) was computed at 30 days only. The debate doc predicts the
gain should shrink with horizon; if the 0.66/0.835 split widens or narrows with
horizon, that distinguishes "policy contamination" from "genuine degradation signal".
The pipeline can produce this slice for every horizon in one pass once W4 is
implemented.

## 6. Relation to the earlier reviews

Nothing in this review contradicts flint, gwen-3-8 or researcher-opus. Concretely:

- Flint's documentation-drift finding is **still open** (W1 above); its other findings
  were fixed in the commits between `edfa60d` and `398f421`.
- Researcher-opus's R1 (importance figure), R2 (188 packing), R4 (last-week snapshots)
  and R9 (scipy) are independently confirmed here (W2, W3, W6, W5) with different
  evidence: the mechanism via `write_json`'s `sort_keys`, a direct panel query for the
  188 values, a first-principles check on the duration-0 row, and a read of
  `pyproject.toml`.
- Researcher-opus's R3 (circularity) is confirmed here with a complementary slice and
  a slightly different number (0.660 vs 0.627) — both below the 0.875 headline.
- The remaining researcher-opus items (R5 validation drives doing three jobs, R6, R7,
  R10, R11) and flint's medium/low items were not re-examined in depth here; this
  review's independent checks all landed on already-known ground, which is itself a
  useful signal: the three earlier reviews did not miss anything I could find.

## 7. Validation performed during this review

- `uv run pytest` — 34 tests pass (~37 s), including the end-to-end synthetic run.
- Re-derived the README's five AUC rows, the gain CIs, the alerting row and the life
  quantiles from `build-arch/metrics.json`; all match.
- Confirmed `build/report/report.md` is the medium run by reading both
  `cohort-summary.json` files.
- Confirmed the importance-figure defect by inspecting key order in
  `build/models/hazard_smart.json`.
- Queried `dataset/dataset.parquet` (June 2025 month) for `smart_188_raw` statistics
  per vendor: Seagate mean 1.09e9 / max 2.2e12, WDC mean 0.0 / max 96, Toshiba and
  HGST entirely null.
- Recomputed the 30-day AUC on the no-critical-counter slice (0.660), the
  with-counter slice (0.835), and the last-week AP (1.0) from
  `build-arch/predictions.parquet` and `snapshots.parquet`.
- Counted failure-day SMART completeness (377/377 populated, 24% grew vs prior day)
  on one month of the raw panel.
- Verified `scipy` is absent from `pyproject.toml` while `survival.py` imports it.

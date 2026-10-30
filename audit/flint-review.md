# Flint Review — hard-drive-analysis-v3

- **Audit date:** 2026-10-25 (session start; artifacts current through commit `edfa60d`)
- **Subject:** `/home/lazy/projects/hard-drive-analysis-v3` — v3 of the Backblaze SMART
  remaining-life study
- **Scope:** pipeline code (`steps/`), shared modules, tests, configs (`pipeline.toml`,
  `config/`), docs, generated results (`build/` medium run, `build-arch/` full run),
  verification gate and evaluation logic.
- **Method:** read-only review of source + docs + generated artifacts, re-ran the test
  suite, queried the produced artifacts with DuckDB, and cross-checked the README's
  headline claims against `build-arch/report/report.md` and `build/metrics.json`.

## 1. Verdict at a glance

The project is in **strong shape**. The rebuild addressed nearly all substantive findings
of the v2 project review (`hard-drive-analysis-v2/PROJECT_REVIEW.md`), the v2 label bug was
fixed in the right direction, the verification gate covers both directions of the failure
window, the evaluation moved to censoring-aware, weighted, drive-level-bootstrap metrics,
and — most importantly — **the full-scale run actually completed** on the 31 GB machine with
the gate passing 26/26 and a 30-minute end-to-end runtime.

The code-level statistics (survival math, weighted AUC/AP/KM/Harrell C, Platt calibration,
trend features) are unit-tested against sklearn / brute force / hand-computed answers, and
all **34 tests pass** (`uv run pytest`, ~38 s including the synthetic end-to-end run).

The main weaknesses found in this review:

1. **High — documentation drift:** the README points at `build/report/report.md` as the home
   of the results, but the full-scale run's outputs live in `build-arch/` (and `build/` holds
   the medium run). The pointer was not updated when commit `edfa60d` moved the full-run
   artifacts into `build-arch/`.
2. **Medium — small code smells that erode the "one contract" principle:** duplicated bin
   edges (`DURATION_BUCKETS`) in `steps/evaluate.py`, hardcoded model labels and an
   arbitrary timing threshold in `steps/report.py`.
3. **Medium — gate bookkeeping:** the `enough_failures_*` checks are always registered with
   severity `warn`, even when they pass, so passing runs surface warnings.
4. **Medium — dependency metadata:** `pyproject.toml` allows `duckdb>=1.5` while the steps
   require `duckdb>=2.0`.

No **critical** correctness bugs were found in the modelling math or the data path; the
trend-window logic was explicitly re-verified and behaves as designed.

## 2. What was done right

### 2.1 Survival framing and censoring (v2 review §3.2 → fixed)

- v2's bug — train drives failing after the cutoff labelled their pre-failure snapshots as
  healthy — is gone. Training drives are now **censored** at `train_end`; the failure after
  the cutoff is *unknown*, never negative. Gate check `labels_match_cohort` recomputes both
  directions and `no_visible_failure_labelled_censored` guards the window.
- Discrete-time hazard with person-period rows, actuarial exposure for censored snapshots
  inside a bin, survival product over bins, `P(fail within H) = 1 - S(H)`, median/10-90% life
  quantiles, restricted mean life.
- Unit tests: event-in-bin, event-on-day-0, censored-inside-bin, flat-survival quantiles,
  Platt recovery. All pass.

### 2.2 Splits (v2 review §3.1, §4.2 → fixed)

- Drive-level split via sha256 `stable_bucket` (not DuckDB `hash()`), plus temporal split
  (`train_end = 2023-12-31`, `test_start = 2024-01-01`), disjointness enforced in the gate.
- Early stopping and the alert threshold are chosen on **validation** drives only; test is
  used once for final numbers.

### 2.3 Verification gate (v2 review §3.4 → rebuilt)

- 26 checks: schema/leak/float/date/duplicate checks, split integrity, weights, labels
  (both directions), time windows, train-vs-test label isolation, feature fill, train-only
  model levels. Gate fails the pipeline on any error.
- Tamper tests in `tests/test_cohort_and_gate.py` inject a v2-style label bug, split leak and
  train-in-test-period row — all caught.

### 2.4 Sampling, weights and calibration (v2 review §4.5 → fixed)

- Inverse-probability sampling weights (failing/healthy fractions, stride + dense windows).
- Tempered training weights (`weight_power = 0.5`) plus per-bin Platt recalibration on
  validation with true weights. This fixed over-confident long-horizon predictions and the
  early-stopping starvation problem.
- Feature schema frozen in `study.toml`, stored in `build/feature-schema.json`, checked by
  the gate and by `load_booster`.

### 2.5 Evaluation design (v2 review §4.3/§4.5 → fixed)

- Drive-level (cluster) bootstrap for every interval, including paired SMART-vs-no-SMART
  gains; row-level resampling rejected.
- PR-AUC added (rare events), Harrell's C for concordance, Kaplan-Meier observed risk,
  weighted Brier.
- Metric implementations validated: AUC/AP against `sklearn.metrics` with sample weights,
  concordance against brute force over all pairs, KM against hand-computed values.

### 2.6 Trend features and leakage

- Trend features are date-keyed via `RANGE BETWEEN INTERVAL n DAYS PRECEDING` windows
  (`test_trend_features_are_date_keyed`); calendar date is not a feature; leak columns
  checked; predictions keep `serial_number` + `date`.

### 2.7 Orchestration, determinism, tests

- Content-hash checkpoints with cascading invalidation, fail-loud workers, declared-input
  verification, `requires` dependency checks, deterministic outputs, progress logs.
- Full test suite green; end-to-end run on synthetic panel green; gate tamper tests green.

### 2.8 Full-scale execution

- Full run on the 31 GB machine (`info/hwspec-archmachine-20261021.md`): gate 26/26,
  ~30 min end to end, training estimate 17.8 GiB vs 23.0 GiB available (guard at 90% → 20.7 GiB
  → passed, ~3 GiB spare; real peak unmeasured, ISSUES #1).
- Headline numbers reproducible from `build-arch/`: SMART beats no-SMART at all 5 horizons
  with bootstrap CIs excluding zero; beats the classic counter rule at all horizons.

## 3. Findings

### 3.1 High

**F1 — README points at the wrong output directory for the full-scale results (documentation).**
- `README.md:17`: "The full tables are in `build/report/report.md`."
- `README.md:76–77`: "Results land in `build/report/report.md`."
- Commit `edfa60d` moved the full-run artifacts into `build-arch/` (added `build-arch/` to
  `.gitignore`, commit message: "build-arch/ holds that run's outputs and stays out of git")
  and rewrote the results section for the full scale — but did not update these pointers.
- Consequence: a reader following the README lands on the medium-scale `build/report/report.md`
  (11,575 drives; 1,837 test drives; 359 failures) while the headline section claims the full
  scale. The full tables actually live in `build-arch/report/report.md`.
- **Recommendation:** change both pointers to `build-arch/report/report.md`.

**F2 — Gate: passing `enough_failures_*` checks are recorded with severity `warn`.**
- `steps/verify.py`: `add(f"enough_failures_{s}", n_ev >= 30, f"{n_ev} failing drives (< 30 is noisy)", "warn")`.
- The severity argument is unconditional; a passing check is then reported as a warning.
- Cosmetic in outcome (gate still fails only on error severity) but confusing in the report and
  in the "26/26 checks passed" summary, which mixes pass/warn reporting.

### 3.2 Medium

**F3 — Duplicated contract constants outside the single contract file.**
- `steps/evaluate.py`: `DURATION_BUCKETS = [0, 7, 14, 30, 60, 90, 180, 365]` duplicates
  `label.bin_edges` from `config/study.toml`.
- `steps/report.py`: `LABELS` hardcodes the four known models; `_timing_verdict` hardcodes a
  ±0.15 mean-deviation threshold; `_days`/`_pct`/`_fmt` are local helpers.
- Risk: the "one contract" principle (`config/study.toml`) is only partially honoured here.

**F4 — Dependency manifest drift.**
- `pyproject.toml` declares `duckdb>=1.5`; pipeline steps require `duckdb>=2.0` (e.g.
  `pipeline.toml:24`, `pipeline.toml:33`). The orchestrator checks step-level `requires`, but
  the project-level floor should match reality.

**F5 — Report step declared non-critical.**
- `pipeline.toml`: `explore` and `report` carry `critical = false`. A failed report step does
  not halt the run; acceptable operationally, but worth an explicit decision (a report that
  silently does not land is a documentation risk).

### 3.3 Low / maintainability

- **F6 — README layout section is incomplete:** it lists `steps/` as "step functions +
  shared modules (common, survival, metrics)", omitting `drives`, `panel`, `verify`, `model`,
  `predict`, `evaluate`, `report`, `explore`.
- **F7 — `report.py` writes `report.md` with `"\n".join(lines)` — no trailing newline.**
- **F8 — `pyproject.toml`: `[tool.uv] package = false` with a `data-pipeline` editable source
  from `../data-pipeline`** — fine, but the external runner is a sibling repo; the README
  references it as `../data-pipeline` (correct).

### 3.4 Results-level observations (not bugs, but worth knowing)

- **Drift (documented OPEN, `docs/ISSUES.md` #9):** full-run test 30-day predicted/observed
  ratio = 2.21 in 2025 (1.15 in 2024, inside the validation range of 0.85–1.32). Deployment
  would need recalibration.
- **False-alarm rate on test:** 1.63% for `hazard_smart` (1% budget set on validation) —
  consistent with the drift story.
- **Precision/recall:** alert precision 4.2%, recall 77% of failing drives flagged in their
  last 30 days (1,379/1,784); base rate 0.12% (30 d), 0.027% (7 d).
- **Remaining-life calibration:** predicted-median share of failures 33.5% (target 50%) at full
  scale; median abs error ~106 days; only ~15.8% of failing snapshots get a median within a
  year; healthy drives → ">1 year" 99.8% of the time.
- **Survivor population** (ISSUES #7, LIMIT) and **365-day horizon measurability** (ISSUES #6,
  LIMIT) remain open design limits.

## 4. Validation performed during this review

- **Test suite:** `pytest` → **34 passed** in ~38 s (synthetic e2e + unit + gate tamper).
- **Gate:** `build-arch/verify-report.json` → passed, 26 checks; warnings only for
  `enough_failures_*` (see F2).
- **Headline claims cross-checked against generated artifacts:**
  - SMART vs no-SMART gains at all 5 horizons exclude zero; 100% of bootstrap rounds favoured
    SMART (full run).
  - SMART vs classic counter rule beats at all horizons (7 d: +0.056 [0.048, 0.063]).
  - Binary vs hazard at 30 d: AUC 0.879 vs 0.875 (CI overlap), C-index 0.780 vs 0.774 —
    consistent with "the curve, not the ranking, is the value".
  - Drift ratios recomputed from `build-arch/metrics.json` calibration rows (1.15x / 2.21x).
- **Trend-window logic re-verified:** the split time-window filter is applied *after* the
  trend windows are computed (windows live in the `f` CTE; the split filter is in the
  `sampled` CTE), so date-keyed trend history is available for the first in-window snapshot.
  No defect found there.

## 5. Overall assessment

**Done right (the substance):**

- The survival modelling approach is coherent and well-motivated (right censoring, bins,
  Platt recalibration, tempered weights).
- The evaluation is defensible: weights everywhere, censoring-aware metrics, cluster
  bootstrap, PR-AUC, KM calibration, early-warning via validation-chosen threshold.
- The gate is strong and tests are meaningful (math unit tests + e2e + tamper tests).
- The full-scale run is real, documented with timings, and guarded by a memory check.

**Done wrong / lacking (the feedback):**

- Documentation is the weakest area: stale output paths after the `build/` → `build-arch/`
  move; incomplete layout; mixed pass/warn bookkeeping.
- A few constants duplicated outside the single contract.
- Minor dependency/manifest and report-writing nits.

**Bottom line:** the scientific pipeline, as executed, is sound and the headline results are
internally consistent and reproducible from the artifacts. The principal actionable item from
this review is the **README output-path fix**, followed by cleaning up the duplicated constants
and the gate's warning tagging.

## 6. Recommendations

1. Fix README paths: `build/report/report.md` → `build-arch/report/report.md` (results) and
   reconcile with `build/report/report.md` for the medium-scale tables.
2. Re-run or hand-fix the verify report wording so only genuinely failing checks carry
   `severity: error` (or stop tagging passing checks `warn`).
3. Move `DURATION_BUCKETS` into `config/study.toml` / `common.py` and have `evaluate` read it.
4. Centralise model display labels in the report step or a config.
5. Bump `duckdb>=2.0` in `pyproject.toml` to match the steps' requirement.
6. Re-open follow-ups from `docs/ISSUES.md` (#6, #7, #9) as tracked work; consider a rolling-origin
   recalibration experiment before deployment.

## 7. Open items (carried from `docs/ISSUES.md`)

- **#6** — 365-day horizon only measurable on 2024 test snapshots (LIMIT).
- **#7** — survivor population / retirement censoring (LIMIT).
- **#9** — test-period drift, OPEN (predicted/observed ratio 2.2x in 2025 at full scale).
- **#10** — model category list depends on sampled train drives (FRAGILE).

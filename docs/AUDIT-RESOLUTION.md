# How v3 resolves the 2026-10 audit

Five reviews in `audit/` looked at v3 between 2026-10-25 and 2026-10-26, mostly at commit
`398f421`: `flint-review.md` (flint), `gwen-3-8-review.md` (gwen),
`glm-4-7-flash-review.md` (glm), `researcher-opus-review.md` (opus) and
`deepseek-v4-1-flash-review.md` (deepseek). Finding numbers below are the reviews' own
(F1, R2, W3, D5, §3.7). On 2026-10-26 Claude re-ran the main numbers on `build-arch/`,
the full-scale run at `398f421`, to check the findings.

The fixes are on branch `audit-fixes`:

| Commit | What |
|---|---|
| `9d0ba01` | Packaging and reproducibility: scipy declared, dataset sha256 pinned, full-run results in git |
| `7eb0c9a` | Report importance figure by gain; single-attribute AUC on reported rows only |
| `6a117c3` | Vendor-packed SMART values decoded; dense days only before visible failures |
| `df47ad7` | Four new gate checks |
| `3de2e4b` | Models: separate validation roles, Platt slope guard, recent recalibration, ablations |
| `e0b1554` | Evaluation and report: IPCW, Uno's C, drive-level AUC, slices, alert budgets, drift, retirement |
| this commit | Documentation (README, METHODOLOGY, ISSUES, this file) |

The fixed code has run at medium scale (2026-10-26). The full-scale numbers in the
README still come from `398f421`. The full rerun needs the 31 GB machine
(docs/ISSUES.md #15).

## Confirmed findings

### Results and reporting

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A1 | The importance figure lists features alphabetically and uses the wrong denominator (opus R1, glm W2) | `report.top_importance` sorts by gain and divides by the total gain over all features. Unit test | `7eb0c9a` |
| A4 | The README points at the medium report for full-scale results (flint F1, glm W1) | README points at `results/full-2026-10-24/report/report.md` for the full run and calls `build/report/report.md` the last local run | this commit |
| A14 | The binary-vs-hazard sentence relies on overlapping intervals (deepseek W4) | The report uses the paired bootstrap difference. README, full run: -0.0043 [-0.0083, +0.0003], binary ahead in 97% of rounds | `e0b1554`, this commit |
| A22 | Documentation nits | METHODOLOGY: the "664 drives report after a failure" row replaced by a measurement (710 drives, 694 HDDs and 16 boot SSDs, report after their first failure row; 46 have two failure rows; 561 are in the full cohort); the 365-day caveat; units; dense days trimmed at `test_start` (by design); Brier skill; the AUC-and-prevalence clause. README layout lists every step module | this commit |

### Data and features

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A2 | Seagate's packed `smart_188_raw` handicaps the rule, and 188 trends are meaningless (opus R2, glm W3) | 188 raw dropped (normalized used) and removed from the critical counters and the trends. While auditing 240-242 as opus asked, Seagate's 240 turned out to be packed too (`msec24hour32`): it keeps its low 32 bits. 241 and 242 are clean. The synthetic panel has packed values | `6a117c3` |
| A7 | `days_in_service` is left-truncated for drives already in service in 2016 (opus R6, glm) | Context feature `left_truncated`. `hazard_usage` gives a context model the power-on hours | `6a117c3`, `3de2e4b` |
| extra | `window_days_*` use `first_value(date)` without `IGNORE NULLS` (gwen §3.7, residual) | Documented in METHODOLOGY §5: the span is to the earliest row of any kind in the window | this commit |

### Models

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A3 | Label circularity is never measured (opus R3, glm W4, deepseek D6) | `hazard_nocritical` ablation (no 5/187/188/197/198). Silent-failure slice at every horizon in `evaluate` and the report | `3de2e4b`, `e0b1554` |
| A8 | Validation drives do three jobs, and the Platt slope is unchecked (opus R5) | Validation drives split by a stable hash (`split.calibration_share`): early stopping vs calibration and alert threshold. A slope <= 0 is refitted with slope 1 and recorded in the model metadata | `3de2e4b`, `e0b1554` |
| A13 | `weight_power` and retirement are unbounded (gwen §3.3-3.4, deepseek D2/D3) | `hazard_smart_w075` / `_w100` sensitivity steps. Retirement diagnostic: predicted risk of drives that leave vs stay, per year | `3de2e4b`, `e0b1554` |

### Evaluation

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A5 | Last-week positives carry PR-AUC (opus R4, glm W6) | Slice "positives >= `min_lead_days` (7) before failure" at every horizon. Alerting counts drives alerted at least 7 days early | `e0b1554` |
| A6 | Capacity covariate shift (opus D11) | Slice >= 16 TB / < 16 TB (`evaluation.capacity_split_tb`). Documented as LIMIT (docs/ISSUES.md #13) | `e0b1554` |
| A9 | Horizon metrics drop censored rows (opus R7) | IPCW ROC-AUC and PR-AUC with intervals. Uno's C next to Harrell's | `e0b1554` |
| A10 | Drift is not gated or corrected (gwen §3.2, glm D2, deepseek W2) | Drift section: validation band, early warning on the last validation year, test years flagged, ratio intervals from the bootstrap. `hazard_smart_recent` recalibrated on the last validation year. Rolling-origin evaluation not done | `3de2e4b`, `e0b1554` |
| A11 | Vendor heterogeneity (deepseek D1, opus D2) | Per-vendor slice at 30 days | `e0b1554` |
| A16 | Precision drops the alerts whose outcome is unknown (deepseek W6) | `unknown_alert_share` and `precision_unknown_as_false` reported | `e0b1554` |
| A17 | Per drive-day vs per drive (deepseek W1) | `auc_drive` column (one random snapshot per drive, drive weights, bootstrap). Units stated in the `evaluate` docstring and in the report | `e0b1554` |
| A19 | One alert budget, no intervals (opus R8) | Budgets 0.1%, 0.3% and 1% with bootstrap intervals | `e0b1554` |
| extra | Concordance on subsampled rows, no interval (glm, opus R7) | Drives sampled whole up to the cap, bootstrap intervals. Vectorised Fenwick tree (same result, faster) | `e0b1554` |
| extra | Concordance scores differ by model (deepseek W3) | Every probability model is also scored by its 30-day risk | `e0b1554` |
| extra | Bootstrap ignores the sampling strata (glm §4) | Failing and healthy drives are resampled separately | `e0b1554` |
| extra | Brier is uninformative (deepseek §4) | Brier skill score against the base-rate forecast | `e0b1554` |

### Gate, tests and code

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A18 | Gate gaps (deepseek W7, opus R11) | Four new checks (26 -> 30), including realised stride density and the dense-day rule. Test that features do not depend on the future | `df47ad7` |
| A20 | The synthetic panel lacks real-data quirks; no unit tests for alerting, life, report (opus R10) | Synthetic quirks (packed 188/240, NULL 187/188 on other vendors, a non-numeric string, silent failures). Tests for `top_importance`, `feature_signal`, IPCW, Uno's C, the censoring Kaplan-Meier, the stratified bootstrap, the fixed-slope Platt fit, feature include/exclude, the memory guard, report helpers | `9d0ba01`, `7eb0c9a`, `6a117c3`, `3de2e4b`, `e0b1554` |
| A21 | Small code items | `DURATION_BUCKETS` replaced by `label.bin_edges` (flint F3, `e0b1554`). `duckdb>=2.0` in `pyproject.toml` (flint F4, `9d0ba01`). The constant "failing drives" column replaced by positive snapshots (`7eb0c9a`). Dead `np.where` removed (`e0b1554`). `n_models_per_month` carried to the cohort and checked by the gate (`9d0ba01`, `df47ad7`). `TRY_CAST` failures counted (`6a117c3`). `explore` single-attribute AUC on filled rows only (`7eb0c9a`). `in_dense` only for failures visible in the split (`6a117c3`). `min_failing_drives` in config (`df47ad7`) | several |

### Reproducibility and packaging

| # | Finding (sources) | Resolution | Commit |
|---|---|---|---|
| A12 | Results are not reproducible from git (gwen §3.1) | `results/full-2026-10-24/` committed. `drive_index` checks the dataset's sha256. `data-pipeline` is still an editable sibling path (needs the owner to publish or pin it) | `9d0ba01` |
| A15 | scipy is used but not declared (opus R9, glm W5) | Declared in `pyproject.toml` and in the train steps' `requires` | `9d0ba01` |

### Judged and left as is

| # | Finding (sources) | Decision |
|---|---|---|
| A23 | `_timing_verdict` normalisation (deepseek W5) | A defensible choice: it divides by the largest possible miss. No change |
| A24 | The article is "to do" | Out of scope for code fixes (docs/ISSUES.md #17) |

## Claims checked and found wrong

No change was made for these:

- **flint F2**, passing `enough_failures_*` checks reported as warnings: a passing check is
  reported as passed whatever its severity.
- **flint F7**, `report.md` has no trailing newline: the generated file ends with one.
- **gwen §3.1**, the `hda` entry point: it does not exist. The project runs through
  `data-pipeline`.
- **gwen §3.8**, `article/research/` is empty: it holds the reference papers.
- **gwen §3.5**, minus the restricted mean under-reports concordance: in the full run the
  30-day risk gives the same C. (At medium scale with the fixed code it gives 0.749
  against 0.737, inside the interval [0.710, 0.763].)
- **gwen §3.7**, trends go stale under gaps: the window is bounded at 30 calendar days,
  so the earliest value can't be older than that. The residual point about
  `window_days_*` is documented (above).
- **gwen P5**, move scikit-learn to the dev group: at the reviewed commit scipy arrived only
  through scikit-learn, and `fit_platt` needs scipy, so the move would have broken
  training. scipy is declared since `9d0ba01`; the move itself was not made.
- **glm W3**, the model's lead over the rule is 77% vs 66% of failing drives: the rule
  flagged 37% (661 of 1,784) in that run, and 1,062 once 188 is removed.
- **glm W6**, last-week 30-day AP = 1.0: the block checked has no negatives, so AP is 1
  by construction.
- **glm §6**, flint's other findings were fixed before `398f421`: they were not.
- **glm D1, deepseek D5**, the survival curve is too flat or optimistic: the direction is
  backwards (drives fail later than predicted, so the model is too pessimistic), and
  per-bin Platt is the more flexible fit.
- **deepseek W1**, drive-level 30-day ROC-AUC of 0.849: that is a single random draw. Ten
  draws give 0.858-0.873. The report now averages 20 draws and gives an interval.
- **glm D4**, the context-only result contradicts the references in `article/research/`:
  the review gives no source for it.

## Not done

These need the 31 GB machine or a decision by the owner:

- **Full-scale rerun with the fixed code.** The README's full-scale numbers are from
  `398f421` (docs/ISSUES.md #15).
- **LICENSE, CI, publishing or pinning `data-pipeline`.** The licence is the owner's
  choice, and CI can't install the runner while it is a sibling path
  (docs/ISSUES.md #16).
- **Rolling-origin evaluation** (docs/ISSUES.md #9), **"leaves the panel" as an event**
  (deepseek D3, docs/ISSUES.md #7) and a **pod-level bootstrap** (opus D7).
- **The article** (docs/ISSUES.md #17).
- **Not addressed in this round:** the rest of flint F3 (`report.py` still hardcodes the
  model labels and the ±0.15 timing tolerance) and flint F5 (`explore` and `report` stay
  `critical = false`).

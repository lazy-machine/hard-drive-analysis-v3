# How v3 resolves the v2 project review

Every finding in `hard-drive-analysis-v2/PROJECT_REVIEW.md` (2026-10-21, commit
`b0969a7`), and what v3 does about it. "Test" names the test that guards the fix, where
one exists.

## §2 Kept from v2

| v2 item | In v3 |
|---|---|
| Declarative step graph | `pipeline.toml`, run by `data-pipeline` |
| Thin orchestrator, topo sort, cycle detection, process per step | Provided by `data-pipeline` (and tested there) |
| Fail-loud worker spawning | `data-pipeline`: a failed critical step halts the run and dumps its output |
| DuckDB for whole-panel work | `drive_index`, `extract` (chunked by month, memory-bounded) |
| Drive-level + temporal split | `cohort` + `snapshots`, checked by `verify` |
| `stable_bucket` (sha256) | `common.stable_bucket` / `stable_unit`, now registered via Arrow, not a `VALUES` literal |
| Deterministic same-day dedup | `extract` (most complete row, then filename) |
| Next-failure semantics | First failure is the event. Rows after it are dropped (documented in METHODOLOGY §1) |
| Missing values as `NaN` | Kept: features are FLOAT with NULL → NaN for LightGBM |
| Model list from config | One `train_*` step per model in `pipeline.toml`. `predict` discovers models from its inputs |
| Verification gate framework | `data_verify:verify`, with project checks in `steps/hdd_checks.py` (§3.4 below) |
| Imbalance handling | Replaced by inverse-probability sampling weights (tempered for training) plus per-bin calibration on validation drives, so probabilities are on the real-world scale |
| Test metric suite, DeLong | Metrics rebuilt around censoring and weights. DeLong replaced by a drive-level bootstrap (§4.3) |
| Issue-log habit | `docs/ISSUES.md` uses the same format |

## §3.1 `--mode full` broken

| Finding | Resolution |
|---|---|
| 1. `dataset_summary` missing imports | Step removed. Its content (per-model counts, AFR) is in `explore`, from the drive index |
| 2. Full mode reuses the small split | Scale lives in `config/sample.toml`, which `cohort` and `snapshots` read as inputs. Content-hash checkpoints rerun them when it changes. There is no mode special case left to get wrong |
| 3. `refined == train + test` can't hold in full mode | No `refined` file. The gate checks invariants that hold at every scale: each snapshot's labels recomputed from the cohort, one split per drive, time windows, weights (`test_gate_*`) |
| 4. Audit can't scale (`n_pos × n_neg`, `4000 × N`) | No O(n²) work. AUC/AP are O(n log n) with one sort reused across bootstrap rounds, the bootstrap yields one round at a time, and concordance uses a Fenwick tree on at most `concordance_max_rows` |
| 5. Correlation sample uses unstable `hash()` and the first few drives | `explore` samples drives with a seeded RNG over *all* train drives |
| 6. Correlated subquery, `VALUES` literal, `LIMIT/OFFSET` batching | Next failure comes from the drive index (a join). Cohort registered as Arrow. Snapshots loaded once, column by column. Panel processed in month chunks and drive batches |

## §3.2 Labels censored at the cutoff

The cutoff no longer turns failures into negatives. Train drives are **censored** at
`train_end`: a snapshot gets `event = 0` and a duration up to the cutoff, and the survival
model treats it as "alive at least this long", not as "healthy". Labels are derived from
the full per-drive history (drive index) at every scale. Tests:
`test_train_failure_after_cutoff_is_censored_not_negative`,
`test_gate_catches_v2_label_bug`.

## §3.3 Orchestrator

| Finding | Resolution |
|---|---|
| Existence-only checkpoints, no cascade | `data-pipeline` checkpoints on code + config + input content and cascades. `test_pipeline_runs_and_caches` checks a second run is fully cached |
| `--step X` can delete everything | Gone. `data-pipeline -o STEP` / `-r STEP` never delete outputs of other steps |
| Declared inputs never checked | `data-pipeline` verifies inputs before running |
| Worker output discarded | Captured output is shown on failure or with `-v`. Long steps also write `build/logs/<step>.log` |
| `null_prevalence` missing dependency | Dependencies are inferred from input/output paths |
| `json.loads` without error handling | No marker files. The gate step raises, and the pipeline halts |
| `--n-samples` passed to every worker | Gone. Steps get only their own `params` |

## §3.4 Verification gate

| Finding | Resolution |
|---|---|
| `row_count_conservation` wrong in full mode | Replaced (see §3.1.3) |
| `label_window_correctness` one-directional | `labels_match_cohort` recomputes event and duration for every row. `no_visible_failure_labelled_censored` checks the other direction explicitly |
| `no_target_leak_column` only checks `failure` | `no_leak_columns_in_features` checks the schema against `common.LEAK_COLUMNS` (ids, labels, dates, failure fields) |
| `feature_alignment` can't fail | `snapshot_columns_match_schema` compares against the frozen schema. Models store feature names and are checked on load |
| `class_balance` duplicate | `failures_present_*` (error) and `enough_failures_*` (warning, < 30 failing drives) |
| `null_rate_bounds` passes when skipped | Feature fill is computed in DuckDB at every scale (`no_empty_features`, `few_sparse_features`) |
| Dates compared as strings | DATE type is checked (`date_is_date_type`) and compared as dates |
| Wrapper exits 0 with no marker | A failed check raises, so the step fails and the pipeline halts. Missing inputs are caught by `data-pipeline` before running |
| Contract constants copied by hand | All read from `config/study.toml` / `sample.toml` / `feature-schema.json` |

## §3.5 Smaller bugs

All in code that no longer exists (`step_dependency_test`, `Style.clear`, the audit's
exit code, the comparison table, the duplicated orchestrator printer, `DEFAULT_MODEL`,
`split_is_fabricated`). Dependencies are declared in `pyproject.toml` with a lockfile, and
`data-pipeline` checks each step's `requires` before running.

## §4 Modelling

| Finding | Resolution |
|---|---|
| 4.1 `date_days` is a feature | Removed. Age = SMART 9 and days in service. `test_models_store_feature_names` asserts no date feature |
| 4.2 Row-level early-stopping split leaks | Early stopping on **validation drives** (separate stable-bucket range) |
| 4.3 Row-level bootstrap / DeLong overstate significance | Drive-level (cluster) bootstrap for every interval, including paired model differences (`test_bootstrap_resamples_whole_drives`) |
| 4.4 Rankings unstable, used as correctness signal | No hyperparameter-preset ranking. Correctness lives in the gate and tests. Model comparisons are about *information* (SMART vs no SMART vs rule), with intervals |
| 4.5 Lag rows are not lag days | Trends use `RANGE ... INTERVAL n DAYS` windows (`test_trend_features_are_date_keyed`) |
| 4.5 Feature set depends on the sample | Fixed feature list in `study.toml`. Model categories from train drives only (`model_levels_from_train_only`) |
| 4.5 Feature identity not stored with the model | LightGBM text models with feature names, plus metadata JSON. `load_booster` asserts they match |
| 4.5 String columns become NaN features | Only curated SMART columns are read, cast with `TRY_CAST` (`smart_18/23` included and tested) |
| 4.5 Row-level only, no PR-AUC, best-F1 threshold tuned on test | PR-AUC, drive-level alert recall, detection by days before failure. Threshold chosen on validation. Predictions keep `serial_number` and `date` |
| 4.5 Demo split is all failing drives | Stratified sample of failing **and** healthy drives, weighted back to real prevalence |
| 4.5 In-sample log-loss over train + val | Only validation log-loss is reported (early-stopping metric) |

## §5 Structure

| Finding | Resolution |
|---|---|
| One shared contract | `config/study.toml` (+ `sample.toml`), loaded and validated by `common.load_study` |
| Two sources of truth for models | `pipeline.toml` only |
| Preprocessor runs on import | Step functions take a context. Nothing runs on import, and modules are unit-tested |
| No tests | `tests/`: synthetic panel with known answers, unit tests, end-to-end run, gate tamper tests |
| No dependency manifest | `pyproject.toml` + `uv.lock` |
| Two output dirs | One: `build/` |
| Repeated `connect()` blocks | `common.connect` |
| Pickled models | LightGBM text format |
| `.pi-glla/` | In `.gitignore` |

## §6 Documentation

v2's docs were not ported. `README.md`, `docs/METHODOLOGY.md` and this file were written
from the v3 code, and the results in the README come from `build/report/report.md`, which
is generated from the metrics.

## §8 Priorities

All nine are done as described above. **8 (run full mode on a bigger machine)** ran on
2026-10-24 on the 31 GB machine in `info/hwspec-archmachine-20261021.md`: 30 minutes end
to end, gate 26/26, every failing HDD in the panel included. Timings and the memory
margin are in `docs/ISSUES.md` #1, and the results are in the README.

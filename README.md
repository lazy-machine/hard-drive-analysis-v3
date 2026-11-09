# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

v3 answers this on Backblaze's public drive-stats panel (646,777,037 daily snapshots of
478,464 drives, 2016-2025) with a survival model, and checks whether SMART really adds
information against a model that doesn't see it. It rebuilds
`../hard-drive-analysis-v2` on the [`data-pipeline`](../data-pipeline) runner and
resolves the v2 project review (see [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md))
and the 2026-10 audit (see [docs/AUDIT-RESOLUTION.md](docs/AUDIT-RESOLUTION.md)).

## Results (full scale, 2026-10-27)

These numbers come from the full-scale run of 2026-10-26/27 with the audit fixes (branch
`audit-fixes`, the step code of `9b77159`). Its full tables are in
[`results/full-2026-10-27/report/report.md`](results/full-2026-10-27/report/report.md), a
committed copy of that run (the original `build-arch/` is local and gitignored).
`build/report/` holds the last local run, whatever its scale: `results.md` has the
headline numbers, `analysis.md` the explanation and the detailed tables. The committed
runs predate this split and keep everything in one `report.md`. The run before
the fixes (2026-10-24, `398f421`) is kept in `results/full-2026-10-24/`. What changed
between the two is at the end of this section.

Cohort: every failing HDD plus a 10% sample of healthy ones, 57,309 drives. Test set:
8,981 drives never seen in training, observed 2024-2025, of which 1,784 fail (825,321
snapshots). The gate ran 30 checks and passed, with one warning (16 cohort drives with
too few rows in their split window for a snapshot). All numbers are weighted back to
real prevalence. The weights do not correct ROC-AUC for prevalence (AUC doesn't change
when every row of a class gets the same weight). They change the mix of drives and days
within each class, and they make PR-AUC, precision, the base rate and calibration
real-world quantities. Brackets are 95% drive-level bootstrap intervals. ROC-AUC is per
drive-day snapshot unless stated.

**1. Yes, SMART carries real failure information.** Against an identical survival model
that only knows the drive's model, capacity and time in service, SMART raises ROC-AUC at
every horizon:

| fails within | no SMART | SMART + context | gain | rule on counters 5, 187, 197, 198 |
|---|---|---|---|---|
| 7 days | 0.606 | **0.906** | +0.300 [0.282, 0.314] | 0.853 |
| 30 days | 0.604 | **0.876** | +0.273 [0.260, 0.288] | 0.823 |
| 90 days | 0.601 | **0.843** | +0.241 [0.225, 0.259] | 0.786 |
| 180 days | 0.593 | **0.814** | +0.221 [0.208, 0.236] | 0.755 |
| 365 days | 0.574 | **0.786** | +0.211 [0.197, 0.228] | 0.722 |

The model beats the classic "any reallocated / pending / uncorrectable sector" rule at
every horizon (+0.053 [0.046, 0.061] at 7 days).

**2. Part of it is the replacement policy.** Backblaze replaces drives when counters 5,
187, 188, 197 or 198 rise, so those counters partly define the failure label. A model
without them (`hazard_nocritical`) still reaches 0.772 [0.760, 0.786] at 30 days. The
full model is ahead by +0.104 [0.096, 0.112], and about 62% of the SMART gain (0.168 of
0.273) remains without those counters. The +0.273 is an upper bound on what SMART adds
beyond the policy.

**3. Silent failures are ranked much worse.** 368 of the 1,784 failing test drives never
show counter 5, 187, 197 or 198 above zero in their test snapshots. On them the SMART
model scores 0.639 [0.608, 0.666] at 30 days (no SMART 0.549, rule 0.473), against 0.938
on the failures with a counter above zero.

**4. It isn't only age and wear.** Context plus the usage counters (4, 9, 12, 193,
240-242) scores 0.654. The full SMART model is ahead by +0.222 [0.211, 0.236].

**5. It works as an early warning, not as an oracle.** Alarm thresholds are set on
validation drives for a false-alarm budget. False alarms and precision are per
drive-day; failing drives count as alerted if they get an alert in their last 30 days:

| budget | model | false alarms on test | precision | failing drives alerted | of them >= 7 days early |
|---|---|---|---|---|---|
| 0.1% | SMART model | 0.22% | 14.6% | 1,021 / 1,784 (57%) | 782 |
| 0.3% | SMART model | 0.61% | 8.3% | 1,264 / 1,784 (71%) | 1,028 |
| 1% | SMART model | 1.55% | 4.4% | 1,372 / 1,784 (77%) | 1,181 |
| 1% | 30-day classifier | 1.88% | 3.8% | 1,412 / 1,784 (79%) | 1,216 |
| 1% | rule | 1.74% | 3.1% | 1,051 / 1,784 (59%) | 874 |

At the 1% budget the SMART model flags 321 more failing drives than the rule, at fewer
false alarms. Its precision of 4.4% is about 36x the 0.12% base rate, so most alerts are
still false: failures are that rare. The classifier flags 40 more drives than the
survival model but also raises more false alarms, so the two are not compared at the
same rate. About 7% of the alerts fall where the panel ends before the outcome is known;
the report gives precision both without them and with them counted as false. Every test
false-alarm rate is above its budget because of the drift in point 9.

**6. The last days carry much of the precision.** Counting as positives only snapshots
at least 7 days before failure, the 30-day ROC-AUC is 0.868 and the PR-AUC 0.079 [0.066,
0.097] instead of 0.124.

**7. "When will it fail?" can only be answered close to the end.** For drives that fail
within a year, the model puts the median remaining life inside that year in 48% of
snapshots taken in the last week, and in only 8.5% of snapshots 6-12 months out. Most
failures leave no SMART trace that early. For healthy drives it says "more than a year"
99.8% of the time. When it does name a day, it is too pessimistic on the test years: 33%
(not 50%) of drives had failed by their predicted median, 6.5% by the 10% day and 76.5%
by the 90% day.

**8. The survival model's value is the curve, not better ranking.** At 30 days the
paired difference in ROC-AUC, survival model minus the plain yes/no classifier, is
-0.001 [-0.004, +0.002]; the survival model is not better in 72% of bootstrap rounds.
Neither ranks clearly better. Over the whole future the classifier's concordance is a
little higher (Harrell's C on the predicted 30-day risk: 0.783 vs 0.773). What the
survival model adds is one consistent answer for every horizon and a remaining-life
estimate.

**9. Drift in 2025, not fixed by recalibrating on the last year.** Predicted / observed
30-day risk is 0.89-1.44 over the validation years (2016-2023), 0.92 in 2023. On test it
is 1.21 [1.11, 1.30] in 2024, inside that band, and 2.28 [1.97, 2.67] in 2025, outside
it. `hazard_smart_recent`, the same trees recalibrated on the 2023 validation snapshots,
gives 1.36 and 2.55, so it makes the drift worse. Of the other feature sets, only the model without
SMART drifts clearly less (1.10 / 1.73). The usage-counter model drifts like the SMART model (1.32 / 2.46) and the
classifier more (1.46 / 3.19). A deployed model would need a different fix
(docs/ISSUES.md #9).

**10. Retirement is informative censoring.** Among drives that never fail, the ones that
leave the panel by the end of the next year carry 1.2-6.5x the mean predicted 30-day risk
of the ones that stay, in every validation year, and 2.25x in test year 2024 (509 drives
left, 5,809 stayed). Drives look riskier before they leave, so the observed failure risk
is an underestimate, and stronger retirement in later years would explain part of the
drift.

**Slices** (30 days). By vendor: HGST 0.923, Seagate 0.895, Toshiba 0.792, WDC 0.827. By
capacity: 0.815 on drives of 16 TB and more, 0.901 below (rule 0.754 vs 0.850); large
drives are rare in training (docs/ISSUES.md #13). Only 5 failing test drives were in
service before the panel starts, too few to measure.

**Training weight power.** At this scale the full inverse-probability weights no longer
starve training: weight power 1.0 stops at iteration 237 (0.5: 595, 0.75: 194) and ranks
like 0.5 (30-day ROC-AUC 0.878 vs 0.876; ahead by 0.006 [0.002, 0.009] at 90 days only).
Power 0.5 keeps the higher PR-AUC: by 0.008-0.031 against 1.0, with an interval above
zero at 4 of 5 horizons.

**Robustness.** ROC-AUC with inverse-probability-of-censoring weights differs from the
known-status ROC-AUC by at most 0.012 (at 365 days: 0.774 vs 0.786). ROC-AUC on one
snapshot per drive is 0.862 at 30 days (0.901 at 7 days). Harrell's / Uno's C on the
expected days survived within a year is 0.766 / 0.760. The Brier skill against a
base-rate forecast is 0.027 at 30 days: at this prevalence Brier says little.

**What matters most:** by share of the total gain in the SMART model, the horizon bin
(21%), capacity (10%), reallocated sectors 5 (10%), pending sectors 197 (9%), the drive
model (8%), uncorrectable errors 187 (7%) and the 30-day growth of counter 5 (4%). The
usage counters 240, 242, 193 and 241 add about 2% each. The ranking is `importance_gain`
in `results/full-2026-10-27/models/hazard_smart.json` and `report/importance.png`.

### What changed since the run before the fixes

Against `results/full-2026-10-24/` (`398f421`):

- The SMART model ranks the same: 30-day ROC-AUC 0.875 then, 0.876 now; 365 days 0.788
  and 0.786.
- The rule is stronger without Seagate's packed 188 values. At the 1% budget it now flags
  1,051 failing drives instead of 661, so the model's lead shrinks from 718 drives to
  321.
- Survival model vs classifier at 30 days: -0.0043 [-0.0083, +0.0003] then, -0.001
  [-0.004, +0.002] now. Early stopping and calibration now use separate halves of the
  validation drives.
- Drift: validation band 0.85-1.32 then, 0.89-1.44 now; test 1.15 / 2.2 then, 1.21 / 2.28
  now.
- The 349 silent failures measured during the audit counted counter 188 too. With
  counters 5, 187, 197 and 198, both runs have 368.
- The importance figure is now sorted by gain.

## Quick start

```bash
uv sync                          # Python 3.13, deps from uv.lock (data-pipeline is ../data-pipeline, editable;
                                 # the data gate, data-verify, comes from its verify extra)
uv run pytest                    # unit + end-to-end tests on a synthetic panel (~40 s)
uv run ruff check steps tests    # lint (config in pyproject.toml)
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date (small scale: ~10 min, the first time)
```

The committed scale is `small`. A first run takes about 6 minutes for `drive_index` plus about
7 minutes for the rest. For the full-scale numbers, set `scale = "full"` in `config/sample.toml`
(about 6 + 66 minutes, 11 GiB of memory; see Scales and hardware).

The panel goes in `dataset/dataset.parquet` (21.8 GB, not in git). Results land in
`build/report/results.md` (numbers) and `build/report/analysis.md` (explanation). Long steps log progress to `build/logs/<step>.log`.

CI (`.github/workflows/test.yml`) runs the linter and the tests on every push and pull
request. It checks out `data-pipeline` next to this repository from the repository
variable `DATA_PIPELINE_REPO` (secret `DATA_PIPELINE_TOKEN` while that repository is
private), which have to be set first (docs/ISSUES.md #16).

## Scales and hardware

The scale is chosen in `config/sample.toml` (`scale = "small" | "medium" | "full"`).
Changing it reruns only what depends on it. The full-panel scan (`drive_index`) is
shared by all scales and stays cached. It takes about 6 minutes, including the sha256
check of the dataset.

| Scale | Drives (failing / healthy kept) | Snapshot stride | Where it runs |
|---|---|---|---|
| small | 4% / 0.4% | 7 days | any machine. ~7 min after `drive_index` (timed with three models) |
| medium | 20% / 2% | 7 days | 15 GB machine. ~22 min after `drive_index` with the seven train steps, of which `evaluate` takes ~11 min. Training estimate 3.7 GiB |
| full | 100% / 10% | 7 days | 15 GB machine. ~66 min after `drive_index` with the seven train steps (2026-10-30), of which `evaluate` takes ~8 min. Training estimate 11.5 GiB, peak used memory 11.0 GiB (docs/ISSUES.md #1) |

Every scale estimates the same real-world numbers: sampled drives and snapshots carry
inverse-probability weights. Smaller scales give wider confidence intervals.

`HDA_MEMORY_FRACTION` (default 0.6) and `HDA_THREADS` tune DuckDB/LightGBM resources
without invalidating checkpoints.

## Pipeline

```
dataset.parquet ─► drive_index ─► cohort ─► extract ─► snapshots ─► verify (gate)
                   (1 full scan)  (split,   (cohort's  (features,     │
                                  sample,   daily rows) labels,       ├─► explore
                                  weights)              weights)      ├─► train_hazard_smart ──────┐
                                                                      ├─► train_hazard_nosmart ────┤
                                                                      ├─► train_binary_30d ────────┤
                                                                      ├─► train_hazard_nocritical ─┼─► predict ─► evaluate ─► report
                                                                      ├─► train_hazard_usage ──────┤
                                                                      ├─► train_hazard_smart_w075 ─┤
                                                                      └─► train_hazard_smart_w100 ─┘
```

| Step | Output | What it does |
|---|---|---|
| `drive_index` | `build/drives.parquet` | Checks the dataset's sha256, then one row per drive: model, capacity, span, first failure. Scans the panel month by month |
| `cohort` | `build/cohort.parquet` | HDDs only. Stable sha256 split by drive (70/10/20). Stratified, weighted sample |
| `extract` | `build/panel/` | The cohort's daily rows: curated SMART columns, deduplicated, cut at the first failure. Counts strings that fail the numeric cast |
| `snapshots` | `build/snapshots.parquet` | Sampled snapshots, date-keyed trend features, right-censored labels |
| `verify` | `build/verify-report.json` | The gate (30 checks): recomputes every label, checks splits, time windows, weights, sampling density, schema, leaks |
| `explore` | `build/explore/` | Failure rate per model, single-attribute signal, correlations, survival by counters |
| `train_*` | `build/models/` | LightGBM text models + metadata (features, params, calibration, importance). `hazard_smart` is the model under test; `hazard_nosmart`, `hazard_nocritical` and `hazard_usage` are ablations; `binary_30d` is the fixed-horizon baseline; `hazard_smart_w075` / `_w100` test the training weight power |
| `predict` | `build/predictions.parquet` | Survival curves → P(fail within 7/30/90/180/365 d), median remaining life, interval. Adds `hazard_smart_recent` (same trees, calibrated on the last validation year) and the rule score |
| `evaluate` | `build/metrics.json`, `*.csv` | Weighted, censoring-aware metrics with drive-level bootstrap intervals, slices, alert budgets, drift, retirement |
| `report` | `build/report/results.md`, `analysis.md` | `results.md`: the run and the headline numbers, one line per table on how to read it. `analysis.md`: the answer in plain language, every detailed table, the figures |

## Layout

```
pipeline.toml        steps and models (the only registry)
config/study.toml    the shared contract: split, label bins, features, evaluation
config/sample.toml   scales
steps/
  drives.py          drive_index, cohort
  panel.py           extract, snapshots
  verify.py          the gate
  explore.py         explore
  model.py           train (every train_* step)
  predict.py         predict
  evaluate.py        evaluate
  report.py          report
  common.py          shared: study contract, stable hashing, DuckDB connections, logs
  survival.py        shared: person-period expansion, Platt calibration, survival curves
  metrics.py         shared: weighted AUC/AP, Kaplan-Meier, IPCW, Harrell's/Uno's C, bootstrap
tests/               synthetic panel, unit tests, end-to-end run, gate tamper tests
results/             committed copies of the full-scale runs (see results/README.md)
docs/                METHODOLOGY.md, ISSUES.md, REVIEW-RESOLUTION.md, AUDIT-RESOLUTION.md
audit/               the 2026-10 reviews by other agents
info/                hardware report of the machine that runs `full`
```

Conventions, kept from v2 and enforced by `data-pipeline`:
- **Never load the panel into pandas.** Whole-panel work is DuckDB, in month chunks.
- **Steps talk only through declared files.** Shared helpers are listed under `watch`.
- **Outputs are deterministic** (sorted, seeded) so unchanged results keep later steps cached.
- **One contract.** A rule that two steps share goes in `config/study.toml`.

## Docs

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): the survival framing, sampling and
  weights, features, comparisons, metrics, limits.
- [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md): every v2 review finding and
  what v3 does about it.
- [docs/AUDIT-RESOLUTION.md](docs/AUDIT-RESOLUTION.md): every finding of the 2026-10
  audit (`audit/`) and the commit that addresses it.
- [docs/ISSUES.md](docs/ISSUES.md): the issue log.

## Licence

MIT, see [LICENSE](LICENSE).

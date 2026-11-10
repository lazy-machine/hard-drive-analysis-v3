# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

v3 answers this on Backblaze's public drive-stats panel (646,777,037 daily snapshots of
478,464 drives, 2016-2025) with a survival model, and checks whether SMART really adds
information against a model that doesn't see it. It rebuilds
`../hard-drive-analysis-v2` on the [`data-pipeline`](../data-pipeline) runner and
resolves the v2 project review (see [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md))
and the 2026-10 audit (see [docs/AUDIT-RESOLUTION.md](docs/AUDIT-RESOLUTION.md)).

## Results (full scale, 2026-11-09)

These numbers come from the full-scale run of 2026-11-09 after the drive-metadata fix
(docs/ISSUES.md #18). Its tables are committed in
[`results/full-2026-11-09-leakfix/report/`](results/full-2026-11-09-leakfix/report/):
`results.md` has the headline numbers, `analysis.md` the explanation and the detailed
tables. `build/report/` holds the last local run, whatever its scale. Earlier full runs
stay in `results/` for comparison (index in [`results/README.md`](results/README.md)).
What changed against the previous README numbers is at the end of this section.

Cohort: every failing HDD plus a 10% sample of healthy ones, 57,309 drives. Test set:
8,981 drives never seen in training, observed 2024-2025, of which 1,784 fail (825,321
snapshots). The gate ran 56 checks: 55 passed, one warned (16 cohort drives with too few
rows in their split window for a snapshot). All numbers are weighted back to
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
| 7 days | 0.606 | **0.904** | +0.297 [0.280, 0.310] | 0.853 |
| 30 days | 0.604 | **0.875** | +0.271 [0.257, 0.287] | 0.823 |
| 90 days | 0.606 | **0.840** | +0.234 [0.218, 0.252] | 0.786 |
| 180 days | 0.600 | **0.810** | +0.210 [0.195, 0.224] | 0.755 |
| 365 days | 0.578 | **0.785** | +0.208 [0.189, 0.224] | 0.722 |

The model beats the classic "any reallocated / pending / uncorrectable sector" rule at
every horizon (+0.051 [0.043, 0.059] at 7 days).

**2. Part of it may be the replacement policy.** Backblaze replaces drives when counters
5, 187, 188, 197 or 198 rise, so those counters partly define the failure label. A model
without them (`hazard_nocritical`) still reaches 0.774 [0.761, 0.788] at 30 days. The
full model is ahead by +0.101 [0.092, 0.109], and about 63% of the SMART gain (0.170 of
0.271) remains without those counters. This is a sensitivity check, not a split of policy
from physics: the dropped counters also measure real damage, and the remaining features
can still track them.

**3. Silent failures are ranked much worse.** 368 of the 1,784 failing test drives never
show counter 5, 187, 197 or 198 above zero in their test snapshots. On them the SMART
model scores 0.634 [0.601, 0.660] at 30 days (no SMART 0.558, rule 0.473), against 0.937
on the failures with a counter above zero.

**4. It isn't only age and wear.** Context plus the usage counters (4, 9, 12, 193,
240-242) scores 0.655. The full SMART model is ahead by +0.219 [0.209, 0.233].

**5. It works as an early warning, not as an oracle.** Alarm thresholds are set on
validation drives for a false-alarm budget. False alarms and precision are per
drive-day; failing drives count as alerted if they get an alert in their last 30 days:

| budget | model | false alarms on test | precision | failing drives alerted | of them >= 7 days early |
|---|---|---|---|---|---|
| 0.1% | SMART model | 0.22% | 14.6% | 1,017 / 1,784 (57%) | 760 |
| 0.3% | SMART model | 0.57% | 8.7% | 1,241 / 1,784 (70%) | 1,006 |
| 1% | SMART model | 1.95% | 3.7% | 1,396 / 1,784 (78%) | 1,209 |
| 1% | 30-day classifier | 2.00% | 3.6% | 1,421 / 1,784 (80%) | 1,226 |
| 1% | rule | 1.74% | 3.1% | 1,051 / 1,784 (59%) | 874 |

At the 1% budget the SMART model flags 345 more failing drives than the rule, with a
little more false alarms (1.95% vs 1.74%). Its precision of 3.7% is about 30x the 0.12%
base rate, so most alerts are still false: failures are that rare. The classifier flags
25 more drives than the survival model at about the same false-alarm rate. About 6% of
the alerts fall where the panel ends before the outcome is known; the report gives
precision both without them and with them counted as false. Every test false-alarm rate
is above its budget because of the drift in point 9.

**6. The last days carry much of the precision.** Counting as positives only snapshots
at least 7 days before failure, the 30-day ROC-AUC is 0.866 and the PR-AUC 0.079 [0.067,
0.097] instead of 0.124.

**7. "When will it fail?" can only be answered close to the end.** For drives that fail
within a year, the model puts the median remaining life inside that year in 49% of
snapshots taken in the last week, and in only 7.4% of snapshots 6-12 months out. Most
failures leave no SMART trace that early. For healthy drives it says "more than a year"
99.8% of the time. When it does name a day, it is too pessimistic on the test years:
30.6% (not 50%) of drives had failed by their predicted median, 5.9% by the 10% day and
75.5% by the 90% day. These shares weight each snapshot by the inverse probability of
staying uncensored until its predicted day; dropping the censored snapshots instead gives
35.2%, 6.9% and 79.2%. Both assume retirement is unrelated to failure (point 10).

**8. A dedicated 30-day classifier ranks a little better at 30 days.** The paired
difference in ROC-AUC, survival model minus the plain yes/no classifier, is -0.006
[-0.009, -0.002]; the classifier is ahead in every bootstrap round. In PR-AUC there is no
clear difference (-0.003 [-0.010, +0.004]). Over the whole future the classifier's
concordance is also a little higher (Harrell's C on the predicted 30-day risk: 0.779 vs
0.771). What the survival model adds is one consistent answer for every horizon and a
remaining-life estimate, at a small cost in 30-day ranking.

**9. Drift in 2025, not fixed by recalibrating on the last year.** Predicted / observed
30-day risk is 0.86-1.35 over the validation years (2016-2023), 0.86 in 2023. On test it
is 1.17 [1.09, 1.28] in 2024, inside that band, and 2.28 [1.98, 2.65] in 2025, outside
it. `hazard_smart_recent`, the same trees recalibrated on the 2023 validation snapshots,
gives 1.42 and 2.76, so it makes the drift worse. The model without SMART drifts least
(1.06 / 1.65), then the usage-counter model (1.13 / 1.91); the classifier drifts more
than the SMART model (1.31 / 2.56). A deployed model would need a different fix
(docs/ISSUES.md #9).

**10. Retirement looks related to health.** Among drives that never fail, the ones that
leave the panel by the end of the next year carry 1.0-3.3x the mean predicted 30-day risk
of the ones that stay in the validation years (above 1 in 7 of 8), and 2.08x in test
year 2024 (509 drives left, 5,809 stayed). Drives look riskier before they leave, which
suggests censoring is informative: the observed failure risk is then too low, by an
amount this check cannot measure, and stronger retirement in later years could explain
part of the drift.

**Slices** (30 days). By vendor: HGST 0.927, Seagate 0.895, Toshiba 0.784, WDC 0.823. By
capacity: 0.810 on drives of 16 TB and more, 0.901 below (rule 0.754 vs 0.850); large
drives are rare in training (docs/ISSUES.md #13). Only 5 failing test drives were in
service before the panel starts, too few to measure.

**Training weight power.** At this scale the full inverse-probability weights no longer
starve training: weight power 1.0 stops at iteration 184 (0.5: 545, 0.75: 230) and ranks
like 0.5 (30-day ROC-AUC 0.877 vs 0.875, no interval excludes zero). Power 0.75 ranks a
little better than 0.5 (0.880 at 30 days, +0.004 to +0.007, an interval above zero at 4
of 5 horizons). Power 0.5 keeps the higher PR-AUC against 1.0: by 0.007-0.035, with an
interval above zero at 3 of 5 horizons.

**Robustness.** ROC-AUC with inverse-probability-of-censoring weights differs from the
known-status ROC-AUC by at most 0.012 (at 365 days: 0.773 vs 0.785). ROC-AUC on one
snapshot per drive is 0.860 at 30 days (0.899 at 7 days). Harrell's / Uno's C on the
expected days survived within a year is 0.759 / 0.752. The Brier skill against a
base-rate forecast is 0.033 at 30 days: at this prevalence Brier says little.

**What matters most:** by share of the total gain in the SMART model, the horizon bin
(22%), the drive model (11%), reallocated sectors 5 (11%), uncorrectable errors 187
(9.5%), pending sectors 197 (9.4%) and the 30-day growth of counters 187 and 5 (4% each).
Capacity is down to 1.3% (see below). The ranking is `importance_gain` in
`results/full-2026-11-09-leakfix/models/hazard_smart.json` and `report/importance.png`.

### What changed since the previous README numbers

The previous numbers came from `results/full-2026-10-27/` (65 features). Two changes
since:

- **Feature list** (2026-11-09, `results/full-2026-11-09/`): `smart_18/23/24_raw`, always
  0, replaced by `smart_23_normalized` and `smart_24_normalized` (64 features). 30-day
  ROC-AUC 0.876 to 0.879.
- **Drive-metadata leak** (this run, docs/ISSUES.md #18): capacity was the maximum over a
  drive's whole life, and a single day of rounded capacities in 2018 made it reveal
  whether the drive was still alive then. Fixed, the 30-day ROC-AUC goes from 0.879 to
  0.875 and capacity's share of the gain from 10.6% to 1.3%. Test snapshots are from
  2024 on, so the leak shaped what the model learned from 2016-2018 train rows rather
  than leaking test labels directly.
- Net effect against 2026-10-27: the SMART gain over no SMART is about the same (+0.273
  then, +0.271 now). The survival model vs classifier difference at 30 days moved from
  -0.001 [-0.004, +0.002] to -0.006 [-0.009, -0.002], so the classifier is now clearly,
  if slightly, ahead. The remaining-life shares are now censoring-weighted (point 7).

## Quick start

```bash
uv sync                          # Python 3.13, deps from uv.lock (data-pipeline is ../data-pipeline, editable;
                                 # the data gate, data-verify, comes from its verify extra)
uv run pytest                    # unit + end-to-end tests on a synthetic panel (~40 s)
uv run ruff check steps tests    # lint (config in pyproject.toml)
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date
```

The panel goes in `dataset/dataset.parquet` (21.8 GB, not in git). Results land in
`build/report/results.md` (numbers) and `build/report/analysis.md` (explanation). Long steps log progress to `build/logs/<step>.log`.

CI (`.github/workflows/test.yml`) runs the linter and the tests on every push and pull
request. It checks out `data-pipeline` next to this repository from the repository
variable `DATA_PIPELINE_REPO`, which has to be set first (docs/ISSUES.md #16).

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

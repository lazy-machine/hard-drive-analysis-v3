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

**How precise are small differences?** The brackets cover the sampling of test drives,
not the training run. Two full runs that differed only in 10 training snapshots (of 7.6
million) moved the 30-day ROC-AUC by 0.002 and the survival-model-minus-classifier
difference from -0.006 [-0.009, -0.002] to -0.001 [-0.004, +0.002]. Read differences of a
few thousandths between models as ties, even when their bracket excludes zero.

**1. Yes, SMART carries real failure information.** Against an identical survival model
that only knows the drive's model, capacity and time in service, SMART raises ROC-AUC at
every horizon:

| fails within | no SMART | SMART + context | gain | rule on counters 5, 187, 197, 198 |
|---|---|---|---|---|
| 7 days | 0.603 | **0.905** | +0.302 [0.284, 0.316] | 0.853 |
| 30 days | 0.603 | **0.877** | +0.273 [0.260, 0.291] | 0.823 |
| 90 days | 0.609 | **0.843** | +0.234 [0.219, 0.253] | 0.786 |
| 180 days | 0.606 | **0.813** | +0.207 [0.194, 0.221] | 0.755 |
| 365 days | 0.585 | **0.787** | +0.203 [0.188, 0.219] | 0.722 |

The model beats the classic "any reallocated / pending / uncorrectable sector" rule at
every horizon (+0.052 [0.045, 0.060] at 7 days).

**2. Part of it may be the replacement policy.** Backblaze replaces drives when counters
5, 187, 188, 197 or 198 rise, so those counters partly define the failure label. A model
without them (`hazard_nocritical`) still reaches 0.770 [0.758, 0.784] at 30 days. The
full model is ahead by +0.106 [0.098, 0.114], and about 61% of the SMART gain (0.167 of
0.273) remains without those counters. This is a sensitivity check, not a split of policy
from physics: the dropped counters also measure real damage, and the remaining features
can still track them.

**3. Silent failures are ranked much worse.** 368 of the 1,784 failing test drives never
show counter 5, 187, 197 or 198 above zero in their test snapshots. On them the SMART
model scores 0.638 [0.608, 0.666] at 30 days (no SMART 0.562, rule 0.473), against 0.939
on the failures with a counter above zero.

**4. It isn't only age and wear.** Context plus the usage counters (4, 9, 12, 193,
240-242) scores 0.654. The full SMART model is ahead by +0.222 [0.211, 0.236].

**5. It works as an early warning, not as an oracle.** Alarm thresholds are set on
validation drives for a false-alarm budget. False alarms and precision are per
drive-day; failing drives count as alerted if they get an alert in their last 30 days:

| budget | model | false alarms on test | precision | failing drives alerted | of them >= 7 days early |
|---|---|---|---|---|---|
| 0.1% | SMART model | 0.21% | 15.3% | 1,020 / 1,784 (57%) | 763 |
| 0.3% | SMART model | 0.57% | 8.7% | 1,246 / 1,784 (70%) | 1,015 |
| 1% | SMART model | 1.87% | 3.8% | 1,391 / 1,784 (78%) | 1,203 |
| 1% | 30-day classifier | 2.22% | 3.3% | 1,426 / 1,784 (80%) | 1,231 |
| 1% | rule | 1.74% | 3.1% | 1,051 / 1,784 (59%) | 874 |

At the 1% budget the SMART model flags 340 more failing drives than the rule, with a
similar false-alarm rate (1.87% vs 1.74%, overlapping intervals). Its precision of 3.8%
is about 32x the 0.12% base rate, so most alerts are still false: failures are that
rare. The classifier flags 35 more drives than the survival model but also raises more
false alarms (2.22%), so the two are not compared at the same rate. About 6.5% of the
alerts fall where the panel ends before the outcome is known; the report gives precision
both without them and with them counted as false. Every test false-alarm rate is above
its budget because of the drift in point 9.

**6. The last days carry much of the precision.** Counting as positives only snapshots
at least 7 days before failure, the 30-day ROC-AUC is 0.868 and the PR-AUC 0.078 [0.065,
0.096] instead of 0.124.

**7. "When will it fail?" can only be answered close to the end.** For drives that fail
within a year, the model puts the median remaining life inside that year in 47.5% of
snapshots taken in the last week, and in only 6.9% of snapshots 6-12 months out. So the
model rarely names a failure day months ahead, even though it still ranks those
snapshots above chance (365-day ROC-AUC 0.787). For healthy drives it says "more than a
year" 99.9% of the time. When it does name a day, it is too pessimistic on the test
years: of the weighted snapshots, 33.7% (not 50%) had failed by their predicted median,
6.0% by the 10% day and 79.8% by the 90% day. These are IPCW shares: a known failure is
weighted by 1 / P(still uncensored on its failure day), a known survivor by 1 / P(still
uncensored the day before its predicted day). They assume censoring is unrelated to the
failure time and to the predicted day, which holds only roughly, since most censoring is
the panel's end. Leaving out the snapshots without a known outcome instead gives 38.3%,
7.0% and 82.5%. Neither corrects for retirement related to health (point 10).

**8. One survival model or a dedicated 30-day classifier: a tie.** At 30 days the
paired difference in ROC-AUC, survival model minus the plain yes/no classifier, is
-0.001 [-0.004, +0.002], and +0.005 [-0.005, +0.015] in PR-AUC. In the run before the
last fix it was -0.006 [-0.009, -0.002]: the apparent classifier advantage disappeared
after a change to 10 training snapshots, so it was training noise. Over the
whole future the classifier's concordance is a little higher (Harrell's C on the
predicted 30-day risk: 0.777 vs 0.771). What the survival model adds is one consistent
answer for every horizon and a remaining-life estimate.

**9. Drift in 2025, not fixed by recalibrating on the last year.** Predicted / observed
30-day risk is 0.86-1.38 over the validation years (2016-2023), 0.86 in 2023. On test it
is 1.18 [1.09, 1.28] in 2024, inside that band, and 2.18 [1.89, 2.51] in 2025, outside
it. `hazard_smart_recent`, the same trees recalibrated on the 2023 validation snapshots,
gives 1.42 and 2.64, so it makes the drift worse. The model without SMART drifts least
(1.07 / 1.66), then the usage-counter model (1.16 / 2.03); the classifier drifts more
than the SMART model (1.34 / 2.82). A deployed model would need a different fix
(docs/ISSUES.md #9).

**10. Retirement looks related to health.** Among drives that never fail, the ones that
leave the panel by the end of the next year carry 0.88-3.17x the mean predicted 30-day
risk of the ones that stay in the validation years (above 1 in 7 of 8), and 2.02x in
test year 2024 (509 drives left, 5,809 stayed). Drives look riskier before they leave,
which suggests censoring is informative: the observed failure risk is then too low, by an
amount this check cannot measure, and stronger retirement in later years could explain
part of the drift.

**Slices** (30 days). By vendor: HGST 0.931, Seagate 0.897, Toshiba 0.779, WDC 0.826. By
capacity: 0.814 on drives of 16 TB and more, 0.902 below (rule 0.754 vs 0.850); large
drives are rare in training (docs/ISSUES.md #13). Only 5 failing test drives were in
service before the panel starts, too few to measure.

**Training weight power.** At this scale the full inverse-probability weights no longer
starve training: weight power 1.0 stops at iteration 191 (0.5: 419, 0.75: 213) and ranks
like 0.5 (30-day ROC-AUC 0.876 vs 0.877, no interval excludes zero). Power 0.75 is ahead
of 0.5 by 0.003-0.005 at 30 and 90 days, a difference within training noise. Power 0.5
keeps the higher PR-AUC against 1.0: by 0.012-0.032, with an interval above zero at all
5 horizons.

**Robustness.** ROC-AUC with inverse-probability-of-censoring weights differs from the
known-status ROC-AUC by at most 0.012 (at 365 days: 0.775 vs 0.787). ROC-AUC on one
snapshot per drive is 0.862 at 30 days (0.900 at 7 days). Harrell's / Uno's C on the
expected days survived within a year is 0.762 / 0.756. The Brier skill against a
base-rate forecast is 0.042 at 30 days: at this prevalence Brier says little.

**What matters most:** by share of the total gain in the SMART model, the horizon bin
(23%), the drive model (11%), reallocated sectors 5 (11%), uncorrectable errors 187
(10%), pending sectors 197 (10%) and the 30-day growth of counters 187 and 5 (4% each).
Capacity is down to 1.4% (see below). The ranking is `importance_gain` in
`results/full-2026-11-09-leakfix/models/hazard_smart.json` and `report/importance.png`.

### What changed since the previous README numbers

The previous numbers came from `results/full-2026-10-27/` (65 features). Two changes
since:

- **Feature list** (2026-11-09, `results/full-2026-11-09/`): `smart_18/23/24_raw`, always
  0, replaced by `smart_23_normalized` and `smart_24_normalized` (64 features). 30-day
  ROC-AUC 0.876 to 0.879.
- **Drive-metadata leak** (docs/ISSUES.md #18): capacity was the maximum over a drive's
  whole life, and a single day of rounded capacities in 2018 made it reveal whether the
  drive was still alive then. Capacity and model now come from each drive's first rows.
  The 30-day ROC-AUC goes from 0.879 to 0.877, and capacity's share of the gain from
  10.6% to 1.4%. Test snapshots are from 2024 on, so the leak shaped what the model
  learned from 2016-2018 train rows rather than leaking test labels directly.

Net effect against 2026-10-27: the SMART gain over no SMART is the same (+0.273), and the
survival model and the classifier still tie at 30 days. The remaining-life shares are now
IPCW (point 7).

## Quick start

```bash
uv sync                          # Python 3.13, deps from uv.lock (data-pipeline is ../data-pipeline, editable;
                                 # the data gate, data-verify, comes from its verify extra)
uv run pytest                    # unit + end-to-end tests on a synthetic panel (~40 s)
uv run ruff check steps tests    # lint (config in pyproject.toml)
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date
```

The panel goes in `dataset/dataset.parquet` (21.8 GiB, not in git). Results land in
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
| `verify` | `build/verify-report.json` | The gate (56 checks at full scale): recomputes every label, checks splits, time windows, weights, sampling density, schema, leaks |
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

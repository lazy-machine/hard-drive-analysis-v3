# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

v3 answers this on Backblaze's public drive-stats panel (646,777,037 daily snapshots of
478,464 drives, 2016-2025) with a survival model, and checks whether SMART really adds
information against a model that doesn't see it. It rebuilds
`../hard-drive-analysis-v2` on the [`data-pipeline`](../data-pipeline) runner and
resolves the v2 project review (see [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md))
and the 2026-10 audit (see [docs/AUDIT-RESOLUTION.md](docs/AUDIT-RESOLUTION.md)).

## Results (full scale, 2026-10-24, before the audit fixes)

These numbers come from the full-scale run of 2026-10-24 at commit `398f421`, before the
audit fixes on branch `audit-fixes`. Its full tables are in
[`results/full-2026-10-24/report/report.md`](results/full-2026-10-24/report/report.md), a
committed copy of that run (the original `build-arch/` is local and gitignored).
`build/report/report.md` holds the last local run, which is now the medium run with the
fixed code (next section). **The full-scale rerun with the fixed code has not been done
yet**: it needs the 31 GB machine.

Cohort: every failing HDD plus a 10% sample of healthy ones, 57,309 drives. Test set:
8,981 drives never seen in training, observed 2024-2025, of which 1,784 fail. All
numbers are weighted back to real prevalence. The weights do not correct ROC-AUC for
prevalence (AUC doesn't change when every row of a class gets the same weight). They
change the mix of drives and days within each class, and they make PR-AUC, precision, the
base rate and calibration real-world quantities. Brackets are 95% drive-level bootstrap
intervals.

**1. Yes, SMART carries real failure information.** Against an identical survival model
that only knows the drive's model, capacity and time in service, SMART raises ROC-AUC at
every horizon:

| fails within | no SMART | SMART + context | gain | classic counter rule |
|---|---|---|---|---|
| 7 days | 0.605 | **0.906** | +0.300 [0.287, 0.315] | 0.850 |
| 30 days | 0.602 | **0.875** | +0.273 [0.259, 0.288] | 0.821 |
| 90 days | 0.604 | **0.841** | +0.237 [0.223, 0.250] | 0.783 |
| 180 days | 0.597 | **0.815** | +0.218 [0.203, 0.237] | 0.752 |
| 365 days | 0.575 | **0.788** | +0.212 [0.196, 0.229] | 0.719 |

The model also beats the classic "any reallocated / pending / uncorrectable sector"
rule at every horizon (+0.056 [0.048, 0.063] at 7 days). Compared with the medium run
of the same code (5x fewer drives), the extra data helped the long horizons most: 365-day ROC-AUC went
from 0.733 to 0.788, 7-day only from 0.898 to 0.906.

**2. It works as an early warning, not as an oracle.** With the alarm threshold set on
validation drives for a 1% false-alarm budget, **1,379 of 1,784 failing test drives
(77%) were flagged in their last 30 days**. Alerts are 4.2% precise, about 35x the
0.12% base rate. So most alerts are still false: failures are that rare. On test the
false-alarm rate came out at 1.6%, not 1%, because of the drift in point 5.

**3. "When will it fail?" can only be answered close to the end.** For drives that fail
within a year, the model already puts the median remaining life inside that year in 47%
of snapshots taken in the last week, but in only 8% of snapshots 6-12 months out. Most
failures leave no SMART trace that early. For healthy drives it says "more than a year"
99.8% of the time. When it does name a day, it is too pessimistic on the test years:
34% (not 50%) of drives had failed by their predicted median, 7% by the 10% day and 76%
by the 90% day.

**4. The survival model's value is the curve, not better ranking.** At 30 days the
plain yes/no classifier ranks as well or slightly better (ROC-AUC 0.879 vs 0.875; paired
difference, survival minus classifier, -0.0043 [-0.0083, +0.0003], classifier ahead in
97% of bootstrap rounds; concordance 0.780 vs 0.774). What the survival model adds is one
consistent answer for every horizon and a remaining-life estimate, which a fixed-horizon
classifier can't give.

**5. Drift in the test years, clearest in 2025.** Predicted vs observed 30-day risk:
on validation drives (same era as training) the yearly ratio ranges from 0.85x to 1.32x
in both directions with no trend. On test it is 1.15x in 2024, inside that range, and
2.2x in 2025, well outside it. Observed failures fell while the fleet aged, which fits
Backblaze retiring risky drives before they fail (docs/ISSUES.md #7). A deployed model
would need periodic recalibration on recent data.

**What matters most:** by gain in that run's SMART model, pending sectors (197),
reallocated sectors (5) and its 30-day growth, and uncorrectable errors (187, raw and
normalized). Usage counters (240 head flying hours, 193 load cycles, 242 LBAs read) add a
little. The ranking is `importance_gain` in
`results/full-2026-10-24/models/hazard_smart.json`. That run's importance figure is
wrong (see below), and `build/explore/feature_signal.csv` belongs to the last local run.

### What the audit fixes change in this run

Measured during the audit from that run's artifacts:

- **The rule baseline was handicapped.** It included Seagate's packed SMART 188 raw
  values, which took 89% of its false-alarm budget on validation. Without 188, at the 1% budget the
  rule flags 1,062 of 1,784 failing test drives at 3.0% precision (false alarms 1.80%),
  not 661 (37%) at 2.0%. The model's lead over the rule is therefore 317 drives, not
  718. The rule column in the table above still includes 188.
- **Drift in 2024** is 1.15x (1.152), not the 1.16x the README used to state.
- **Binary vs survival model:** the old wording relied on overlapping intervals. The
  paired difference is in point 4.
- **The importance figure** (`report/importance.png`) shows the first 20 features in
  alphabetical order instead of the top 20 by gain.

## Results with the audit fixes (medium scale, 2026-10-26)

The fixed code (branch `audit-fixes`, commit `e0b1554`) at medium scale: 11,575 drives
(20% of failing and 2% of healthy drives), 5x fewer than full scale, so intervals are
wider. Test: 1,837 drives, 359 of them failing, 168,704 snapshots. The gate ran 30
checks and passed, with one warning (3 cohort drives with 1-2 rows and no snapshot).
Full tables: `build/report/report.md`. ROC-AUC at 30 days unless stated, per drive-day.

**SMART still helps.** The SMART model scores 0.860 [0.840, 0.881] against 0.592 without
SMART, a gain of +0.268 [0.236, 0.300]. The rule on counters 5, 187, 197 and 198 (188
removed) scores 0.812.

**Part of it is the replacement policy.** Backblaze replaces drives when counters 5, 187,
188, 197 or 198 rise, so those counters partly define the failure label. A model without
them (`hazard_nocritical`) still reaches 0.757 [0.730, 0.784]. The full model is ahead by
+0.103 [0.081, 0.127], and about 62% of the SMART gain (0.165 of 0.268) remains without
those counters. The +0.268 is an upper bound on what SMART adds beyond the policy.

**Silent failures are ranked much worse.** 72 of the 359 failing test drives never show
a critical counter above zero in their test snapshots. On them the SMART model scores
0.608 [0.554, 0.668] (no SMART 0.529, rule 0.472), against 0.924 on the failures with a
counter above zero. In the full run (measured during the audit) 349 of 1,784 failing test drives are
silent, and the SMART model scores 0.627 on them.

**The last days carry much of the precision.** Counting as positives only snapshots at
least 7 days before failure, ROC-AUC is 0.848 and PR-AUC 0.066 instead of 0.112. (Full
run: PR-AUC 0.080 instead of 0.127.)

**It isn't only age and wear.** Context plus the usage counters (4, 9, 12, 193, 240-242)
scores 0.635. The full SMART model is ahead by +0.225.

**Survival model vs 30-day classifier:** +0.002 [-0.003, 0.008]; the survival model is
not better in 27% of bootstrap rounds. Neither ranks clearly better.

**Training weight power.** 0.75 ranks like 0.5 at 30 days (0.859, difference +0.001
[-0.004, 0.008]) and slightly better at 90-365 days (by 0.006-0.009). 0.5 keeps a higher
PR-AUC at 7 days. Full weights (1.0) score 0.835 and stop at iteration 11, against 149
for 0.5: the starvation of docs/ISSUES.md #8.

**Alert budgets** (SMART model, threshold set on validation drives; false alarms and
precision per drive-day, failing drives alerted in their last 30 days per drive):

| budget | false alarms on test | precision | failing drives alerted | of them >= 7 days early |
|---|---|---|---|---|
| 0.1% | 0.22% | 13.5% | 195 / 359 | 142 |
| 0.3% | 0.54% | 8.6% | 234 / 359 | 188 |
| 1% | 1.64% | 3.9% | 270 / 359 | 228 |
| 1%, rule | 1.97% | 2.6% | 211 / 359 | 167 |

About 7% of the model's alerts fall where the panel ends before the outcome is known.
The report shows precision both without them and with them counted as false.

**Drift is not fixed by recalibrating on the last year.** Predicted / observed 30-day
risk is 0.79-1.86 over the validation years (2016-2023) and 0.91 in 2023. On test it is
1.46 [1.19, 1.82] in 2024 and 2.02 [1.48, 2.72] in 2025, outside the band.
`hazard_smart_recent`, the same trees recalibrated on the 2023 validation snapshots,
gives 1.49 and 2.04. The models without SMART drift less: no SMART 1.22 / 1.55, usage
counters 1.07 / 1.39.

**Retirement is informative censoring.** Among drives that never fail, the ones that
leave the panel by the end of the next year carry 2.2-9.0x the mean predicted 30-day risk
of the ones that stay, in every validation year except 2019 (1.06). In test year 2024 the
ratio is 3.3 (94 drives left, 1,196 stayed). Drives look riskier before they leave, so
the observed failure risk is an underestimate.

**Slices.** By vendor: HGST 0.885, Seagate 0.889, Toshiba 0.743, WDC 0.863 (29 failing
drives). By capacity: 0.830 on drives of 16 TB and more, 0.884 below (rule 0.733 vs
0.845); large drives are rare in training. Drives already in service when the panel
starts are 16.5% of train drives; in test only 3 such drives fail, too few to measure.

**Robustness.** ROC-AUC with inverse-probability-of-censoring weights differs from the
known-status ROC-AUC by 0.001-0.013 (most at 365 days: 0.726 vs 0.739). ROC-AUC on one
snapshot per drive is 0.869 at 30 days (0.916 at 7 days). Harrell's / Uno's C is 0.737 /
0.726. The Brier skill against a base-rate forecast is about 0.01 at 30 days: at this
prevalence Brier says little.

**Remaining life** is still too pessimistic: 4.9% of drives failed by their predicted 10%
day, 27.4% by the median and 50.4% by the 90% day.

## Quick start

```bash
uv sync                          # Python 3.13, deps from uv.lock (data-pipeline is ../data-pipeline, editable)
uv run pytest                    # unit + end-to-end tests on a synthetic panel (~40 s)
uv run ruff check steps tests    # lint (config in pyproject.toml)
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date
```

The panel goes in `dataset/dataset.parquet` (21.8 GB, not in git). Results land in
`build/report/report.md`. Long steps log progress to `build/logs/<step>.log`.

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
| full | 100% / 10% | 7 days | 31 GB machine (`info/hwspec-archmachine-20261021.md`). ~30 min end to end with three models (2026-10-24). Training estimated 17.8 GiB with 23 GiB free. With the fixed code `evaluate` alone is expected to take ~45 min |

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
| `report` | `build/report/report.md` | The answer in plain language, with figures |

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
results/             committed copy of the full-scale run of 2026-10-24 (see results/README.md)
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

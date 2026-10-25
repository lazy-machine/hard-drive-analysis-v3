# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

v3 answers this on Backblaze's public drive-stats panel (646,777,037 daily snapshots of
478,464 drives, 2016-2025) with a survival model, and checks whether SMART really adds
information against a model that doesn't see it. It rebuilds
`../hard-drive-analysis-v2` on the [`data-pipeline`](../data-pipeline) runner and
resolves the v2 project review (see [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md)).

## Results (full scale, 2026-10-24)

Cohort: every failing HDD plus a 10% sample of healthy ones, 57,309 drives. Test set:
8,981 drives never seen in training, observed 2024-2025, of which 1,784 fail. All
numbers are weighted back to real prevalence. Brackets are 95% drive-level bootstrap
intervals. The full tables are in `build/report/report.md`.

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
(5x fewer drives), the extra data helped the long horizons most: 365-day ROC-AUC went
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
plain yes/no classifier ranks as well (ROC-AUC 0.879 vs 0.875, overlapping intervals;
concordance 0.780 vs 0.774). What the survival model adds is one consistent answer for
every horizon and a remaining-life estimate, which a fixed-horizon classifier can't give.

**5. Drift in the test years, clearest in 2025.** Predicted vs observed 30-day risk:
on validation drives (same era as training) the yearly ratio ranges from 0.85x to 1.32x
in both directions with no trend. On test it is 1.16x in 2024, inside that range, and
2.2x in 2025, well outside it. Observed failures fell while the fleet aged, which fits
Backblaze retiring risky drives before they fail (docs/ISSUES.md #7). A deployed model
would need periodic recalibration on recent data.

**What matters most:** pending sectors (197), reallocated sectors (5) and their 30-day
growth, and uncorrectable errors (187, raw and normalized). Usage counters (240 head
flying hours, 193 load cycles, 242 LBAs read) add a little. See
`build/explore/feature_signal.csv` and the importance figure in the report.

## Quick start

```bash
uv sync                          # Python 3.13, deps from uv.lock (data-pipeline is ../data-pipeline, editable)
uv run pytest                    # unit + end-to-end tests on a synthetic panel (~40 s)
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date
```

The panel goes in `dataset/dataset.parquet` (21.8 GB, not in git). Results land in
`build/report/report.md`. Long steps log progress to `build/logs/<step>.log`.

## Scales and hardware

The scale is chosen in `config/sample.toml` (`scale = "small" | "medium" | "full"`).
Changing it reruns only what depends on it. The full-panel scan (`drive_index`) is
shared by all scales and stays cached.

| Scale | Drives (failing / healthy kept) | Snapshot stride | Where it runs |
|---|---|---|---|
| small | 4% / 0.4% | 7 days | any machine. ~7 min after `drive_index` (~5 min, once) |
| medium | 20% / 2% | 7 days | 15 GB machine. ~8 min after `drive_index` (3.5 GB peak) |
| full | 100% / 10% | 7 days | 31 GB machine (`info/hwspec-archmachine-20261021.md`). ~30 min end to end including `drive_index`. Training estimated 17.8 GiB with 23 GiB free |

Every scale estimates the same real-world numbers: sampled drives and snapshots carry
inverse-probability weights. Smaller scales give wider confidence intervals.

`HDA_MEMORY_FRACTION` (default 0.6) and `HDA_THREADS` tune DuckDB/LightGBM resources
without invalidating checkpoints.

## Pipeline

```
dataset.parquet ─► drive_index ─► cohort ─► extract ─► snapshots ─► verify (gate)
                   (1 full scan)  (split,   (cohort's  (features,     │
                                  sample,   daily rows) labels,       ├─► explore
                                  weights)              weights)      ├─► train_hazard_smart ─┐
                                                                      ├─► train_hazard_nosmart├─► predict ─► evaluate ─► report
                                                                      └─► train_binary_30d ───┘
```

| Step | Output | What it does |
|---|---|---|
| `drive_index` | `build/drives.parquet` | One row per drive: model, capacity, span, first failure. Scans the panel month by month |
| `cohort` | `build/cohort.parquet` | HDDs only. Stable sha256 split by drive (70/10/20). Stratified, weighted sample |
| `extract` | `build/panel/` | The cohort's daily rows: curated SMART columns, deduplicated, cut at the first failure |
| `snapshots` | `build/snapshots.parquet` | Sampled snapshots, date-keyed trend features, right-censored labels |
| `verify` | `build/verify-report.json` | The gate: recomputes every label, checks splits, time windows, weights, schema, leaks |
| `explore` | `build/explore/` | Failure rate per model, single-attribute signal, correlations, survival by counters |
| `train_*` | `build/models/` | LightGBM text models + metadata (features, params, importance) |
| `predict` | `build/predictions.parquet` | Survival curves → P(fail within 7/30/90/180/365 d), median remaining life, interval |
| `evaluate` | `build/metrics.json`, `*.csv` | Weighted, censoring-aware metrics with drive-level bootstrap intervals |
| `report` | `build/report/report.md` | The answer in plain language, with figures |

## Layout

```
pipeline.toml        steps and models (the only registry)
config/study.toml    the shared contract: split, label bins, features, evaluation
config/sample.toml   scales
steps/               step functions + shared modules (common, survival, metrics)
tests/               synthetic panel, unit tests, end-to-end run, gate tamper tests
docs/                METHODOLOGY.md, REVIEW-RESOLUTION.md, ISSUES.md
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
- [docs/ISSUES.md](docs/ISSUES.md): the issue log.

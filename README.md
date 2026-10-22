# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

v3 answers this on Backblaze's public drive-stats panel (646,777,037 daily snapshots of
478,464 drives, 2016-2025) with a survival model, and checks whether SMART really adds
information against a model that doesn't see it. It rebuilds
`../hard-drive-analysis-v2` on the [`data-pipeline`](../data-pipeline) runner and
resolves the v2 project review (see [docs/REVIEW-RESOLUTION.md](docs/REVIEW-RESOLUTION.md)).

<!-- RESULTS -->

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
| small | 4% / 0.4% | 7 days | any machine. Minutes once `drive_index` is cached |
| medium | 20% / 2% | 7 days | 15 GB machine. Tens of minutes |
| full | 100% / 5% | 14 days | sized for 31 GB (`info/hwspec-archmachine-20261021.md`). **Not run yet** |

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

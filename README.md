# Hard Drive Analysis v3

**Can the metrics `smartctl` reports (SMART attributes) predict how much life a hard
drive has left, and when it will probably fail?**

This project answers the question on Backblaze's public drive-stats panel: 646,777,037
daily snapshots of 478,464 drives, 2016-2025. It trains a survival model on SMART
attributes and compares it with the same model without SMART. The steps run on the
[`data-pipeline`](../data-pipeline) runner.

## Results

Full-scale run of 2026-11-09. The test set has 8,981 drives never seen in training,
observed in 2024-2025; 1,784 of them fail. Brackets are 95% bootstrap intervals over
drives.

ROC-AUC per horizon:

| fails within | no SMART | SMART + context | gain | rule on counters 5, 187, 197, 198 |
|---|---|---|---|---|
| 7 days | 0.603 | **0.905** | +0.302 [0.284, 0.316] | 0.853 |
| 30 days | 0.603 | **0.877** | +0.273 [0.260, 0.291] | 0.823 |
| 90 days | 0.609 | **0.843** | +0.234 [0.219, 0.253] | 0.786 |
| 180 days | 0.606 | **0.813** | +0.207 [0.194, 0.221] | 0.755 |
| 365 days | 0.585 | **0.787** | +0.203 [0.188, 0.219] | 0.722 |

"No SMART" knows only the drive's model, capacity and time in service. The rule is "any
reallocated, pending or uncorrectable sector".

What the run shows:

- **SMART carries real failure information.** It raises ROC-AUC at every horizon and
  beats the rule at every horizon.
- **Part of the gain may be Backblaze's replacement policy.** Backblaze replaces drives
  when counters 5, 187, 188, 197 or 198 rise. Without those counters the model still
  reaches 0.770 at 30 days, which keeps about 61% of the SMART gain.
- **Silent failures are ranked much worse.** 368 failing test drives never show one of
  the four rule counters above zero. The model scores 0.638 on them at 30 days, against
  0.939 on the other failures.
- **It is not only age and wear.** A model with context and usage counters scores 0.654
  at 30 days.
- **It works as an early warning, not as an oracle.** With a 1% false-alarm budget the
  model alerts on 1,391 of the 1,784 failing drives (78%), 1,203 of them at least 7 days
  early. The rule alerts on 1,051. Precision is 3.8%, about 32 times the 0.12% base
  rate, so most alerts are still false.
- **"When will it fail?" can only be answered close to the end.** In the last week the
  model puts the median remaining life inside the next year in 47.5% of snapshots. At
  6-12 months before failure it does so in 6.9%.
- **A survival model and a 30-day classifier tie.** The 30-day ROC-AUC difference is
  -0.001 [-0.004, +0.002]. The survival model adds one consistent answer for every
  horizon and a remaining-life estimate.
- **The model drifts in 2025.** Predicted over observed 30-day risk is 1.18 in 2024 and
  2.18 in 2025. Recalibrating on 2023 makes it worse.
- **Retirement looks related to health.** Healthy drives that leave the panel carried
  2.02 times the predicted risk of the ones that stayed (test year 2024). The observed
  failure risk is then probably too low.

Differences of a few thousandths between models are within training noise: five trainings
of the reference model with different seeds gave a 30-day ROC-AUC of 0.871 to 0.877.

Every table and the full explanation are in
[`results/full-2026-11-11/report/`](results/full-2026-11-11/report/)
(`results.md` and `analysis.md`). Earlier runs are indexed in
[`results/README.md`](results/README.md).

## Quick start

```bash
uv sync                          # Python 3.13; data-pipeline is ../data-pipeline, editable
uv run pytest                    # tests on a synthetic panel (~40 s)
uv run ruff check steps tests    # lint
uv run data-pipeline -n          # what would run, and why
uv run data-pipeline             # run everything that is out of date
```

The panel goes in `dataset/dataset.parquet` (21.8 GiB, not in git). Results land in
`build/report/results.md` (numbers) and `build/report/analysis.md` (explanation). Long
steps log progress to `build/logs/<step>.log`.

CI (`.github/workflows/test.yml`) runs the linter and the tests on every push and pull
request. It needs the repository variable `DATA_PIPELINE_REPO`, and the secret
`DATA_PIPELINE_TOKEN` while that repository is private.

## Scales

Set `scale` in `config/sample.toml`. The default is `small`. Changing it reruns only
what depends on it. The first run also scans the whole panel once (`drive_index`, about
6 minutes), and that scan stays cached for every scale.

| Scale | Drives kept (failing / healthy) | Time after `drive_index` | Memory |
|---|---|---|---|
| small | 4% / 0.4% | ~7 min | any machine |
| medium | 20% / 2% | ~22 min | 3.7 GiB training estimate |
| full | 100% / 10% | ~66 min | 11.0 GiB peak |

Sampled drives and snapshots carry inverse-probability weights, so every scale
estimates the same real-world numbers. Smaller scales give wider intervals.

`HDA_MEMORY_FRACTION` (default 0.6) and `HDA_THREADS` tune DuckDB and LightGBM resources
without invalidating checkpoints.

## Pipeline

```
dataset.parquet ─► drive_index ─► cohort ─► extract ─► snapshots ─► verify ─► explore
                                                                      │
                                                                      └─► train_* (7 models) ─► predict ─► evaluate ─► report
```

| Step | Output | What it does |
|---|---|---|
| `drive_index` | `build/drives.parquet` | Checks the dataset's sha256, then writes one row per drive |
| `cohort` | `build/cohort.parquet` | HDDs only. Splits by drive (70/10/20) and draws the weighted sample |
| `extract` | `build/panel/` | The cohort's daily rows, deduplicated and cut at the first failure |
| `snapshots` | `build/snapshots.parquet` | Sampled snapshots with trend features and right-censored labels |
| `verify` | `build/verify-report.json` | The gate: recomputes every label and checks splits, weights, schema and leaks |
| `explore` | `build/explore/` | Failure rate per model, single-attribute signal, correlations |
| `train_*` | `build/models/` | LightGBM models. `hazard_smart` is the model under test; the others are ablations and baselines |
| `predict` | `build/predictions.parquet` | Survival curves, failure probability per horizon, median remaining life |
| `evaluate` | `build/metrics.json`, `*.csv` | Weighted, censoring-aware metrics with bootstrap intervals |
| `report` | `build/report/` | `results.md` with the headline numbers, `analysis.md` with the explanation |

## Layout

```
pipeline.toml        steps and models
config/study.toml    the shared contract: split, label bins, features, evaluation
config/sample.toml   scales
steps/               the code of each step, plus shared helpers
tests/               synthetic panel, unit tests, end-to-end run, gate tamper tests
results/             committed copies of the full-scale runs
docs/METHODOLOGY.md  survival framing, sampling and weights, features, metrics, limits
article/             the theoretical study and its research notes
```

Rules the code follows:

- **Never load the panel into pandas.** Whole-panel work is DuckDB, in month chunks.
- **Steps talk only through declared files.**
- **Outputs are deterministic** (sorted, seeded), so unchanged results keep later steps cached.
- **One contract.** A rule that two steps share goes in `config/study.toml`.

## Licence

MIT, see [LICENSE](LICENSE).

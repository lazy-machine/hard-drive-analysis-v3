# Results

Small artifacts of the full-scale runs, copied from `build-arch/` or `build/` (both
gitignored). All use `scale = "full"`: all failing drives and 10% of healthy drives, 57,309 cohort
drives.

| Folder | Run | Code |
|---|---|---|
| `full-2026-10-31-engines/` | 2026-10-31, this fork: the reference models plus the engines of [docs/ENGINES.md](../docs/ENGINES.md) | branch `engines` |
| `full-2026-10-30/` | 2026-10-30 on a 15 GiB machine; same metrics as `full-2026-10-27/` within 5e-7 | `09ebfdd` |
| `full-2026-10-27/` | 2026-10-26/27, the numbers in the README | branch `audit-fixes`, step code of `9b77159` |
| `full-2026-10-24/` | 2026-10-24, before the audit fixes | `398f421` |

Dataset: `dataset/dataset.parquet` (last modified 2026-10-17, before all runs), sha256
`d43984e8200893ebdd1bc739cabff8e05dc759aeb572dc2adb5aaad29e40b556`. The run of
2026-10-27 checked it (`logs/drive_index.log`).

Model files (`build/models/*.txt`) and parquet tables are not included.
`full-2026-10-27/` and `full-2026-10-30/` also keep the step logs, the feature schema and the two small
`explore` tables. In `full-2026-10-30/`, `drive_index` was cached, so its log is from the run that built the cached drive index.

`full-2026-10-31-engines/` keeps the same files plus the engine models' metadata (`models/*.json`, with the network's scaling and encoding but not its weights). Its reference models were cached from an earlier run on the same code and data, so their logs are from that run.

Known defects of the run of 2026-10-24, fixed on `audit-fixes`: `report/importance.png`
lists the first 20 features alphabetically instead of the top 20 by gain, and the rule
baseline (`rule_counters`) includes Seagate's packed SMART 188 raw values.

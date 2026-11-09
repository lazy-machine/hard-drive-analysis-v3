# Results

Small artifacts of the full-scale runs, copied from `build-arch/` or `build/` (both
gitignored). All use `scale = "full"`: all failing drives and 10% of healthy drives, 57,309 cohort
drives.

| Folder | Run | Code |
|---|---|---|
| `full-2026-11-09/` | 2026-11-09, 64 features instead of 65: `smart_18/23/24_raw` (always 0) replaced by `smart_23_normalized` and `smart_24_normalized` (docs/ISSUES.md #1, issue #9). The gate no longer warns `features.constant`. Reference-model ROC-AUC at 30 days 0.879 (0.876 before) | `539bb95` |
| `full-2026-10-30/` | 2026-10-30 on a 15 GiB machine; same metrics as `full-2026-10-27/` within 5e-7 | `09ebfdd` |
| `full-2026-10-27/` | 2026-10-26/27, the numbers in the README | branch `audit-fixes`, step code of `9b77159` |
| `full-2026-10-24/` | 2026-10-24, before the audit fixes | `398f421` |

Dataset: `dataset/dataset.parquet` (last modified 2026-10-17, before all runs), sha256
`d43984e8200893ebdd1bc739cabff8e05dc759aeb572dc2adb5aaad29e40b556`. The run of
2026-10-27 checked it (`logs/drive_index.log`).

Model files (`build/models/*.txt`) and parquet tables are not included.
`full-2026-10-27/`, `full-2026-10-30/` and `full-2026-11-09/` also keep the step logs, the feature schema and the two small
`explore` tables. In `full-2026-10-30/` and `full-2026-11-09/`, `drive_index` was cached, so its log is from the run that built the cached drive index. The run of 2026-11-09 was interrupted twice by a server restart and resumed from its checkpoints, so its step times are not one continuous run.

Known defects of the run of 2026-10-24, fixed on `audit-fixes`: `report/importance.png`
lists the first 20 features alphabetically instead of the top 20 by gain, and the rule
baseline (`rule_counters`) includes Seagate's packed SMART 188 raw values.

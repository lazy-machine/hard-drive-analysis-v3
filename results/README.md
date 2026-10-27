# Results

Small artifacts of the full-scale runs, copied from `build-arch/` (which is gitignored).
Both use `scale = "full"`: all failing drives and 10% of healthy drives, 57,309 cohort
drives.

| Folder | Run | Code |
|---|---|---|
| `full-2026-10-27/` | 2026-10-26/27, the numbers in the README | branch `audit-fixes`, step code of `9b77159` |
| `full-2026-10-24/` | 2026-10-24, before the audit fixes | `398f421` |

Dataset: `dataset/dataset.parquet` (last modified 2026-10-17, before both runs), sha256
`d43984e8200893ebdd1bc739cabff8e05dc759aeb572dc2adb5aaad29e40b556`. The run of
2026-10-27 checked it (`logs/drive_index.log`).

Model files (`build/models/*.txt`) and parquet tables are not included.
`full-2026-10-27/` also keeps the step logs, the feature schema and the two small
`explore` tables.

Known defects of the run of 2026-10-24, fixed on `audit-fixes`: `report/importance.png`
lists the first 20 features alphabetically instead of the top 20 by gain, and the rule
baseline (`rule_counters`) includes Seagate's packed SMART 188 raw values.

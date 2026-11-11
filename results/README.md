# Results

Small artifacts of the full-scale runs, copied from `build-arch/` or `build/` (both
gitignored). All use `scale = "full"`: all failing drives and 10% of healthy drives, 57,309 cohort
drives.

| Folder | Run | Code |
|---|---|---|
| `full-2026-11-11/` | 2026-11-10/11 on a 15 GiB machine (Ryzen 5 4600G), the numbers in the README and the article. Same code as `full-2026-11-09-leakfix/` plus four extra seeds of the reference model and of the 30-day classifier, and new metrics: full follow-up, alerts per drive, calibration by group, seed spread. Every metric shared with `full-2026-11-09-leakfix/` matches within 1.1e-4 (all but one within 5e-6). Ran end to end at commit `f397236` (training, predictions); `explore`, `evaluate` and `report` were then rerun on the same predictions to add the firmware-model slice, per-drive alerts on one weekly schedule and per calendar window, remaining-life intervals, time-in-service bands, per-split counts, the first alert at any lead time, the seed replicates of the per-drive comparison and the operator's any-counter criterion (`logs/pipeline-rerun-evaluate*.log`); the archived tables come from commit `8127c46`. Gate 55/56 passed, one warning | `f397236` (run), `8127c46` (evaluation), data-pipeline `39fb430` |
| `full-2026-11-09-leakfix/` | 2026-11-09 on a 31 GiB machine (Ryzen 7 5700X), the numbers in the README until 2026-11-11. Same 64 features, with the drive-metadata leak fixed: model and capacity from each drive's first rows (capacity rounded to 10 GB; the model's usual capacity for the 10 drives that report none). Remaining-life calibration also IPCW. Reference-model ROC-AUC at 30 days 0.877. Ran end to end without resuming; gate 55/56 passed, one warning. An intermediate version of this folder (rounded lifetime maximum, NULL for the 10 drives; 30-day ROC-AUC 0.875) is in the git history | commit `51dc4a4`, data-pipeline `974499a` |
| `full-2026-11-09/` | 2026-11-09, 64 features instead of 65: `smart_18/23/24_raw` (always 0) replaced by `smart_23_normalized` and `smart_24_normalized` (issue #9). The gate no longer warns `features.constant`. Reference-model ROC-AUC at 30 days 0.879 (0.876 before). Has the drive-metadata leak | `539bb95` |
| `full-2026-10-30/` | 2026-10-30 on a 15 GiB machine; same metrics as `full-2026-10-27/` within 4e-5 (all but 12 values within 5e-7) | `09ebfdd` |
| `full-2026-10-27/` | 2026-10-26/27, the README numbers until 2026-11-09 | branch `audit-fixes`, step code of `9b77159` |
| `full-2026-10-24/` | 2026-10-24, before the audit fixes | `398f421` |

Dataset: `dataset/dataset.parquet` (last modified 2026-10-17, before all runs), sha256
`d43984e8200893ebdd1bc739cabff8e05dc759aeb572dc2adb5aaad29e40b556`. The run of
2026-10-27 checked it (`logs/drive_index.log`).

Model files (`build/models/*.txt`) and parquet tables are not included.
All runs keep their numeric tables, model metadata and verification results. The runs
from 2026-10-27 onward also keep the feature schema and two small `explore` tables.

Only `full-2026-11-11/`, the current reference run, and `full-2026-11-09-leakfix/`, the previous one, keep local
figures and a complete set of step logs. Older reports provide clickable links to their original figure pages at commit
`2dc47742252d827c7ce3c5927efa19dc95424bcc`; the images and superseded logs remain in git history.
The 2026-10-27 `logs/drive_index.log` stays here as the dataset checksum record.

In the 2026-10-30 and 2026-11-09 runs, `drive_index` was cached. The 2026-11-09 run
was interrupted twice by a server restart and resumed from checkpoints, so the step times in its archived logs are not one continuous run.

Known defects of the run of 2026-10-24, fixed on `audit-fixes`: the archived `report/importance.png`
lists the first 20 features alphabetically instead of the top 20 by gain, and the rule
baseline (`rule_counters`) includes Seagate's packed SMART 188 raw values.

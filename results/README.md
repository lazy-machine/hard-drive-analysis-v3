# Results

Small artifacts from the full-scale run of 2026-10-24, copied from `build-arch/`
(which is gitignored). The run was made at commit `398f421` with `scale = "full"`
(all failing drives, 10% of healthy drives, 57,309 cohort drives). It predates the
audit fixes on branch `audit-fixes`, so a rerun on that branch may give different numbers.

Dataset: `dataset/dataset.parquet` (last modified 2026-10-17, before the run), sha256
`d43984e8200893ebdd1bc739cabff8e05dc759aeb572dc2adb5aaad29e40b556`.

Model files (`build/models/*.txt`), parquet tables and logs are not included.

Known defects of this run, fixed on `audit-fixes`: `report/importance.png` lists the first
20 features alphabetically instead of the top 20 by gain, and the rule baseline
(`rule_counters`) includes Seagate's packed SMART 188 raw values.

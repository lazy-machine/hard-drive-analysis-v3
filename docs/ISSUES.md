# Known issues

The running issue log. Same format as v2: tags, status, detail. Add an entry whenever
something surprises you, and close it with how it was verified.

| Tag | Meaning |
|---|---|
| **OPEN** | Not solved yet |
| **FRAGILE** | Works, but easy to break. Read before changing the code around it |
| **CONFUSE** | Behaviour that breaks common sense and costs time |
| **SLOW** | Known slow path, mitigated |
| **LIMIT** | A property of the data or method, not a bug. State it when reporting results |

---

### 1. Full scale has not been run
- **Tags:** OPEN
- **Detail:** `scale = "full"` in `config/sample.toml` is sized for the 31 GB machine
  (`info/hwspec-archmachine-20261021.md`) but has only been estimated, not run. Training
  checks available memory first and stops with a message naming the knobs to turn
  (`healthy_fraction`, `stride_days`). Run it there with `tail -f build/logs/*.log` and
  record the timings here.

### 2. A single GROUP BY over the whole panel spills tens of GB
- **Tags:** SLOW, CONFUSE
- **Status:** mitigated
- **Detail:** `GROUP BY serial_number` over all 646M rows spilled more than 21 GB of
  temp files and ran for over 10 minutes on the 15 GB box, while one month takes about
  2 s. Year-sized chunks were also slow in 2024-2025 (more drives per day). `drive_index`
  and `extract` therefore work month by month (`chunk_months` param). Spill files go to
  `build/tmp/`, never `/tmp`, which is a 7.8 GB tmpfs here.

### 3. DuckDB 2.0 API differences
- **Tags:** CONFUSE
- **Detail:** relations have no `fetchone()` (use `.fetchall()[0]`), and
  `con.execute()` leaves an open result that blocks the connection until fully
  fetched. All code uses `con.sql(...).fetchall()` (`common.scalar`).

### 4. First run hashes the 22 GB panel
- **Tags:** SLOW
- **Detail:** `data-pipeline` fingerprints inputs by content. The first run (or one
  after `rm -rf build`, which deletes the hash cache in `build/.pipeline`) spends about
  80 s hashing `dataset/dataset.parquet`. Later runs reuse the hash while the file's
  size and mtime are unchanged.

### 5. Worker output is only shown at the end
- **Tags:** CONFUSE
- **Detail:** `data-pipeline` captures each step's stdout and prints it only on failure
  (or with `-v`) once the step ends. For progress, follow `build/logs/<step>.log`.

### 6. The 365-day horizon is only measurable on 2024 snapshots
- **Tags:** LIMIT
- **Detail:** the panel ends 2025-12-31. A test snapshot needs a year of follow-up
  (or a failure) to have a known 365-day status, so that horizon uses roughly the first
  half of the test period. `evaluate` skips any horizon where the known-status rows
  are all one class and says so in the report.

### 7. Retirement is treated as non-informative censoring
- **Tags:** LIMIT
- **Detail:** drives that leave the panel without a failure row are censored. If
  Backblaze retires drives *because* they look unhealthy, the model sees fewer
  failures than really happen, and risk is underestimated. The data can't confirm or
  rule this out.

### 8. The model category list depends on the sampled train drives
- **Tags:** FRAGILE
- **Detail:** the top-30 drive models are counted over *sampled* train drives, so a
  different scale can give a slightly different category list (by design: no test
  information). Category codes are therefore stored in `build/feature-schema.json` and
  checked by the gate. Never compare model files across scales.

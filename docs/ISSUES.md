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

### 1. Full scale needs most of the 31 GB machine
- **Tags:** FRAGILE
- **Status:** run on 2026-10-24 on the 31 GB machine (`info/hwspec-archmachine-20261021.md`),
  gate 26/26, with the same code as the repository (only `scale` differed).
- **Detail:** 30 min end to end from an empty `build/`:

  | step | time | size |
  |---|---|---|
  | drive_index | 204 s | 478,464 drives |
  | extract | 238 s | 58.7M panel rows for 57,309 drives |
  | snapshots | 56 s | 7.62M train, 1.08M val, 0.83M test |
  | train_hazard_smart | 609 s | 48.2M survival rows, best iteration 785 |
  | train_hazard_nosmart | 402 s | best iteration 754 |
  | train_binary_30d | 114 s | best iteration 992 |
  | predict, evaluate, rest | 3.5 min | |

  The projection held: 8.7M train+val snapshots (projected 9.3M), 55M survival rows
  (58M). `train_hazard_smart` estimated **17.8 GiB with 23.0 GiB available**. The guard
  stops at 90% of available memory (20.7 GiB), so there were only about 3 GiB to spare: a
  browser or a second job on that machine can trip it. The real peak was not recorded,
  because the logs only hold the estimate. If the guard fires, close other programs or
  lower `healthy_fraction` in `config/sample.toml`. If `snapshots` runs short of memory,
  raise `batches` on `extract` in `pipeline.toml`.

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
  rule this out. If retirement became more aggressive over time, observed failures in
  later years fall below what a model trained on earlier years expects, which matches
  the drift in #9.

### 8. Full inverse-probability weights starve training
- **Tags:** CONFUSE
- **Status:** fixed (`weight_power = 0.5` + per-bin calibration, METHODOLOGY §4)
- **Detail:** with the true weights the SMART model stopped at iteration 34 and had a
  *worse* validation loss than the no-SMART model. Its 1-year predictions for the
  riskiest 1% were ~100% against ~46% observed. Verified on validation drives only
  (test untouched). If you change the sampling fractions, recheck `weight_power` there.

### 9. Test-period drift: predicted risk too high in 2024-2025
- **Tags:** LIMIT, OPEN
- **Detail:** calibration over time (report), predicted / observed 30-day risk. At full
  scale, validation years range from 0.85x to 1.32x in both directions with no trend.
  Test is 1.16x in 2024, inside that range, and 2.2x in 2025, well outside it. (Medium
  scale: 1.25x and 1.8x, with wider noise.) The test false-alarm rate is 1.6% against a
  1% budget for the same reason. Possible causes: retirement of risky drives (#7), fleet
  changes. Next step: recalibrate on the most recent pre-test year, or add a
  rolling-origin evaluation.

### 10. The model category list depends on the sampled train drives
- **Tags:** FRAGILE
- **Detail:** the top-30 drive models are counted over *sampled* train drives, so a
  different scale can give a slightly different category list (by design: no test
  information). Category codes are therefore stored in `build/feature-schema.json` and
  checked by the gate. Never compare model files across scales.

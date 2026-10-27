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
- **Status:** stated in the report since `e0b1554`
- **Detail:** the panel ends 2025-12-31. A test snapshot needs a year of follow-up
  (or a failure) to have a known 365-day status, so that horizon uses roughly the first
  half of the test period. The horizons are therefore measured on different calendar
  cohorts. The report says so under the discrimination table and gives, per horizon, the
  date of the last known-healthy snapshot it uses. `evaluate` skips any horizon where the
  known-status rows are all one class and says so in the report.

### 7. Retirement is informative censoring
- **Tags:** LIMIT
- **Status:** measured (`evaluate` retirement section, medium scale 2026-10-26)
- **Detail:** drives that leave the panel without a failure row are censored, which
  assumes leaving is unrelated to health. `evaluate` compares, per split and year, the
  mean predicted 30-day risk of never-failing drives that leave by the end of the next
  year with those that stay. At medium scale the drives that leave carry 2.2-9.0x the
  risk in every validation year from 2016 to 2023 except 2019 (1.06), and 3.3x in test
  year 2024 (94 left, 1,196 stayed). So the censoring is informative: Backblaze retires
  drives that look unhealthy, the model sees fewer failures than really happen, and risk
  is underestimated. If retirement became more aggressive over time, observed failures in
  later years fall below what a model trained on earlier years expects, which matches
  the drift in #9. The ratio has no interval. Treating "leaves the panel" as an event of
  its own (a competing risk) was not tried.

### 8. Full inverse-probability weights starve training
- **Tags:** CONFUSE
- **Status:** fixed (`weight_power = 0.5` + per-bin calibration, METHODOLOGY §4).
  Sensitivity verified at medium scale (2026-10-26)
- **Detail:** with the true weights the SMART model stopped at iteration 34 and had a
  *worse* validation loss than the no-SMART model. Its 1-year predictions for the
  riskiest 1% were ~100% against ~46% observed. Verified on validation drives only
  (test untouched). Since `3de2e4b` two steps report other powers on test:
  `hazard_smart_w075` ranks like 0.5 (30-day ROC-AUC 0.859 vs 0.860, difference +0.001
  [-0.004, 0.008]), and `hazard_smart_w100` is worse (0.835, difference +0.025 [0.014,
  0.039]) and stops at iteration 11, against 149 for 0.5 and 117 for 0.75. If you change
  the sampling fractions, recheck `weight_power` there.

### 9. Test-period drift: predicted risk too high in 2024-2025
- **Tags:** LIMIT, OPEN
- **Status:** flagged by `evaluate` and tested with a recent recalibration (`3de2e4b`,
  `e0b1554`). Not solved
- **Detail:** calibration over time (report), predicted / observed 30-day risk. At full
  scale (2026-10-24, before the audit fixes), validation years range from 0.85x to 1.32x
  in both directions with no trend. Test is 1.15x in 2024, inside that range, and 2.2x
  in 2025, well outside it. The test false-alarm rate is 1.6% against a 1% budget for the
  same reason. With the fixed code at medium scale the validation band is 0.79-1.86, 2023
  is 0.91, and test is 1.46 [1.19, 1.82] in 2024 and 2.02 [1.48, 2.72] in 2025.
  `evaluate` now flags test years outside the validation band and checks whether the last
  validation year already leaves the band of the earlier ones (it doesn't). Recalibrating
  on 2023 (`hazard_smart_recent`) gives 1.49 and 2.04, so it does not remove the drift.
  The models without SMART drift less (no SMART 1.22 / 1.55, usage counters 1.07 / 1.39).
  Possible causes: retirement of risky drives (#7), fleet changes. Next step: a
  rolling-origin evaluation (train up to year Y, test on Y+1), not done yet.

### 10. The model category list depends on the sampled train drives
- **Tags:** FRAGILE
- **Detail:** the top-30 drive models are counted over *sampled* train drives, so a
  different scale can give a slightly different category list (by design: no test
  information). Category codes are therefore stored in `build/feature-schema.json` and
  checked by the gate. Never compare model files across scales.

### 11. Vendor-packed raw SMART values
- **Tags:** LIMIT, FRAGILE
- **Status:** handled for 188 and 240 (`6a117c3`)
- **Detail:** some raw values are not counts. Seagate packs several 16-bit fields into
  `smart_188_raw` (2.9% of Seagate snapshots >= 65536, up to 3.4e12), and other vendors
  report it as NULL. Seagate's `smart_240_raw` carries a milliseconds field above bit 32
  (`msec24hour32`, 1.1% of Seagate snapshots >= 2^32, against a maximum of 75,184 hours
  on the other vendors). 188 now uses the normalized value only and is out of the rule's
  critical counters, where its packed values took 89% of the validation false-alarm budget (full-scale run of 2026-10-24). 240
  keeps its low 32 bits (`features.raw_low_bits`). 241 and 242 were checked and are
  clean. When you add a raw attribute to `features.raw`, look at its per-vendor
  distribution first: a packed value looks like a huge counter.

### 12. Label circularity and silent failures
- **Tags:** LIMIT
- **Status:** measured (`hazard_nocritical`, silent-failure slice; medium scale 2026-10-26)
- **Detail:** Backblaze replaces drives when counters 5, 187, 188, 197 or 198 rise, and a
  replaced drive is recorded as failed, so these counters partly define the label.
  `hazard_nocritical` drops them (raw, normalized and trends). At 30 days it scores
  0.757 [0.730, 0.784] against 0.860 for `hazard_smart` and 0.592 without SMART: about
  62% of the SMART gain (0.165 of 0.268) remains without them. The full gain is an upper
  bound on what SMART adds beyond the replacement policy. 72 of the 359 failing test drives
  are silent (no critical counter above zero in any test snapshot). On them the SMART
  model's 30-day ROC-AUC is 0.608 [0.554, 0.668] (no SMART 0.529, rule 0.472), against
  0.924 on the other failing drives. In the full run of 2026-10-24, 349 of 1,784 failing
  test drives are silent and the SMART model scores 0.627 on them.

### 13. Capacity covariate shift
- **Tags:** LIMIT
- **Detail:** drives of 16 TB and more are about 10% of train weight but about 50% of
  test weight: the fleet moved to large drives after the training era. At medium scale
  the SMART model's 30-day ROC-AUC is 0.830 on them and 0.884 below 16 TB (rule 0.733 vs
  0.845). `evaluate` reports both sides (`evaluation.capacity_split_tb`). State it when
  quoting a single test number.

### 14. `evaluate` is slow
- **Tags:** SLOW
- **Status:** measured at medium scale (2026-10-26)
- **Detail:** with eight probability models, the slices and the bootstrap, `evaluate`
  took 664 s at medium scale: discrimination 130 s, slices 290 s, concordance 233 s. The
  rest of the medium run after `drive_index` took about 10 minutes (each hazard model
  trains in 30-53 s). Concordance runs a vectorised Fenwick tree per bootstrap round on
  at most `concordance_max_rows` (300,000) rows; the other sections grow with the number
  of test snapshots, about 5x more at full scale. Expect about 45 minutes there.

### 15. The full-scale rerun with the fixed code is pending
- **Tags:** OPEN
- **Status:** the owner will run it on the 31 GB machine (decided 2026-10-26). This
  machine has about 13 GiB available, below the 17.8 GiB training estimate.
- **Detail:** the full-scale numbers in the README come from the run of 2026-10-24 at
  `398f421` (`results/full-2026-10-24/`), before the audit fixes. The fixed code has run
  only at medium scale. A full rerun needs the 31 GB machine (#1). It has seven train
  steps instead of three, and `evaluate` is slower (#14). After the rerun, copy its small artifacts into a new
  `results/` folder and update the README.

### 16. `data-pipeline` is an editable sibling path
- **Tags:** OPEN
- **Status:** CI and a linter added on 2026-10-26. `.github/workflows/test.yml` runs
  `uv run ruff check steps tests` and `uv run pytest -q` on every push and pull request.
  The linter also runs locally (config in `pyproject.toml`). MIT licence added on
  2026-10-26 (`LICENSE`), the owner's choice.
- **Detail:** `pyproject.toml` takes `data-pipeline` from `../data-pipeline` as an
  editable path, so a fresh clone can't `uv sync` without that sibling checkout. The
  workflow works around it: it checks the orchestrator out into `data-pipeline/` next to
  this repository, from the repository variable `DATA_PIPELINE_REPO` (optional
  `DATA_PIPELINE_REF`, and the secret `DATA_PIPELINE_TOKEN` if the orchestrator is
  private). The orchestrator has no remote yet (confirmed by the owner on 2026-10-26).
  Until it has one and the variable is set, the job stops at its first step. Publishing
  `data-pipeline`, or pinning it to a git URL with a commit, would let a fresh clone
  `uv sync` on its own.

### 17. The article is not started
- **Tags:** OPEN
- **Detail:** `article/main-article.md` holds only "to do". The reference papers are in
  `article/research/`. Write it after the full-scale rerun (#15), so it quotes the
  fixed numbers.

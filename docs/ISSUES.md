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

### 1. Full scale needed most of the 31 GB machine
- **Tags:** FRAGILE
- **Status:** resolved on 2026-10-30. A full-scale run at `09ebfdd` finished on a 15 GiB,
  12-thread machine (`debianmachine`) with every training step on row-wise histograms.
  It took 3,935 s with `drive_index` cached. The largest training estimate was 11.5 GiB
  against an 11.9-12.1 GiB budget. Used memory, sampled every 15 s, peaked at 11.0 GiB,
  and available memory never fell below 4.7 GiB. Every metric in `build/metrics.json`
  matches `results/full-2026-10-27/` within 5e-7, with the same best iterations. Earlier
  runs were on the 31 GB machine (`info/hwspec-archmachine-20261021.md`) on
  2026-10-24 (`398f421`, three models) and on 2026-10-26/27 with the audit fixes (seven
  train steps, gate 30 checks with one warning; `results/full-2026-10-27/`).
- **Still fragile:** the training estimates sit 0.4-0.6 GiB under the guard's budget on
  15 GiB, so other programs running at the same time can trip it.
- **Detail:** the first run took 30 min end to end from an empty `build/`:

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

  The run with the fixes took about 85 min of step time after `drive_index` (391 s):
  `extract` 261 s, `snapshots` 55 s, the seven train steps 115-502 s each (2,352 s in
  all), `predict` 179 s and `evaluate` 2,196 s. The largest training estimate was
  16.6 GiB with 22.4 GiB available.

  The 15 GiB run of 2026-10-30 took 3,935 s: `extract` 488 s, `snapshots` 78 s,
  `verify` 148 s, `explore` 60 s, the seven train steps 137-551 s each (2,479 s in all),
  `predict` 197 s and `evaluate` 476 s. The gate ran 54 checks with two warnings:
  `smart_18_raw`, `smart_23_raw` and `smart_24_raw` are constant in train, and 16 cohort
  drives have no snapshot.

  Resolved on 2026-11-09 (issue #9): the three raw columns are a placeholder 0 in the
  whole panel, so the cast loses nothing. 23 and 24 carry their signal in the normalized
  value (11 and 99 drives leave 100; 1 and 28 of them in train), so they now enter as
  `smart_23_normalized` and `smart_24_normalized`; the data is small and harmless. 18 is
  constant in both forms and is no longer a feature. The feature list is now 64 columns.
  Full-scale runs before `results/full-2026-11-09/` have 65. The gate check stays on.

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
- **Status:** measured (`evaluate` retirement section; medium scale 2026-10-26, full
  scale 2026-10-27)
- **Detail:** drives that leave the panel without a failure row are censored, which
  assumes leaving is unrelated to health. `evaluate` compares, per split and year, the
  mean predicted 30-day risk of never-failing drives that leave by the end of the next
  year with those that stay. At medium scale the drives that leave carry 2.2-9.0x the
  risk in every validation year from 2016 to 2023 except 2019 (1.06), and 3.3x in test
  year 2024 (94 left, 1,196 stayed). At full scale the ratio is 1.2-6.5x in every
  validation year and 2.25x in test year 2024 (509 left, 5,809 stayed). So the censoring
  is informative: Backblaze retires
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
  0.039]) and stops at iteration 11, against 149 for 0.5 and 117 for 0.75. At full scale
  (2026-10-27) the starvation is gone: power 1.0 stops at iteration 237 (0.5: 595, 0.75:
  194) and ranks like 0.5 (30-day ROC-AUC 0.878 vs 0.876), while 0.5 keeps the higher
  PR-AUC (by 0.008-0.031, interval above zero at 4 of 5 horizons). The starvation
  depends on how many failing drives the sample has. If you change the sampling
  fractions, recheck `weight_power` there.

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
  At full scale with the fixed code (2026-10-27) the validation band is 0.89-1.44, 2023
  is 0.92, and test is 1.21 [1.11, 1.30] in 2024 (inside the band) and 2.28 [1.97, 2.67]
  in 2025. The 2023 recalibration makes it worse (1.36 / 2.55). Only the model without
  SMART drifts clearly less (1.10 / 1.73); the usage-counter model drifts like the SMART
  model (1.32 / 2.46), so the medium-scale hint that usage counters drift less did not
  hold. Every test false-alarm rate is above its budget (1.55% at 1%). Possible causes: retirement of risky drives (#7), fleet changes. Next step: a
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
- **Status:** measured (`hazard_nocritical`, silent-failure slice; medium scale 2026-10-26,
  full scale 2026-10-27)
- **Detail:** Backblaze replaces drives when counters 5, 187, 188, 197 or 198 rise, and a
  replaced drive is recorded as failed, so these counters partly define the label.
  `hazard_nocritical` drops them (raw, normalized and trends). At 30 days it scores
  0.757 [0.730, 0.784] against 0.860 for `hazard_smart` and 0.592 without SMART: about
  62% of the SMART gain (0.165 of 0.268) remains without them. The full gain is an upper
  bound on what SMART adds beyond the replacement policy. 72 of the 359 failing test drives
  are silent (no critical counter above zero in any test snapshot). On them the SMART
  model's 30-day ROC-AUC is 0.608 [0.554, 0.668] (no SMART 0.529, rule 0.472), against
  0.924 on the other failing drives. At full scale `hazard_nocritical` scores 0.772
  [0.760, 0.786] against 0.876 and 0.604 (62% of the gain, 0.168 of 0.273, remains), and
  368 of 1,784 failing test drives are silent: the SMART model scores 0.639 [0.608,
  0.666] on them (no SMART 0.549, rule 0.473) against 0.938 on the others. The 349
  silent drives measured during the audit on the run of 2026-10-24 counted 188 as a
  critical counter; without it that run has 368 too.

### 13. Capacity covariate shift
- **Tags:** LIMIT
- **Detail:** drives of 16 TB and more are about 10% of train weight but about 50% of
  test weight: the fleet moved to large drives after the training era. At medium scale
  the SMART model's 30-day ROC-AUC is 0.830 on them and 0.884 below 16 TB (rule 0.733 vs
  0.845). At full scale: 0.815 and 0.901 (rule 0.754 vs 0.850). `evaluate` reports both
  sides (`evaluation.capacity_split_tb`). State it when
  quoting a single test number.

### 14. `evaluate` is slow
- **Tags:** SLOW
- **Status:** measured at medium scale (2026-10-26) and full scale (2026-10-27)
- **Detail:** with eight probability models, the slices and the bootstrap, `evaluate`
  took 664 s at medium scale: discrimination 130 s, slices 290 s, concordance 233 s. The
  rest of the medium run after `drive_index` took about 10 minutes (each hazard model
  trains in 30-53 s). Concordance runs a vectorised Fenwick tree per bootstrap round on
  at most `concordance_max_rows` (300,000) rows; the other sections grow with the number
  of test snapshots, about 5x more at full scale. At full scale it took 2,196 s:
  discrimination 623 s, slices 1,328 s, concordance 215 s.

### 15. The full-scale rerun with the fixed code
- **Status:** closed. Run by the owner on the 31 GB machine on 2026-10-26/27, with the step code
  of `9b77159` (the step code hashes in `.pipeline/state.json` match those of the medium
  run on this branch). Gate: 30 checks passed, one warning.
- **Detail:** the small artifacts are in `results/full-2026-10-27/`, and the README's
  results section quotes them. The run before the fixes stays in
  `results/full-2026-10-24/` for comparison.

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
  private). Since 2026-11-09 the orchestrator is at `lazy-machine/data-pipeline` and the
  variable is set, so CI runs. `DATA_PIPELINE_REF` is unset, so CI tests against the
  orchestrator's default branch, not a fixed commit; `results/README.md` records the
  orchestrator commit of each full run. Pinning it to a git URL with a commit would let a
  fresh clone `uv sync` on its own and make CI reproducible.
- **Local race:** `uv run` reinstalls the editable `data-pipeline` whenever its
  `pyproject.toml` is newer than the install. If that happens while a pipeline is running
  (for example `uv run pytest` after editing the orchestrator), workers started during the
  reinstall fail with `No module named data_pipeline`. Seen on 2026-11-09: 20 test setup
  errors during a full run, gone on the next run. Run tests with `.venv/bin/python -m
  pytest` while a pipeline is running, or don't edit the orchestrator during a run.

### 17. The article draft
- **Tags:** OPEN
- **Status:** draft committed on 2026-10-29 (`644ef26`).
- **Detail:** `article/main-article.md` is a full draft of the technical report in pt-BR,
  written to `article/ARTICLE.md` and `article/writing-guide.md`. It quotes the
  full-scale numbers of `results/full-2026-11-09-leakfix/` (updated on 2026-11-09 from
  `results/full-2026-10-27/`). The author line is still
  a `[PREENCHER: ...]` placeholder. The reference papers are listed in
  `article/references.md`; the local copies in `article/research/` are gitignored, so a
  fresh clone does not have them.

### 18. Drive metadata leaked later rows into `capacity_tb` and `model_code`
- **Tags:** CLOSED
- **Status:** fixed on 2026-11-09 after two reviews; full-scale rerun the same day
  (`results/full-2026-11-09-leakfix/`). `results/full-2026-11-09/` still has the leak.
- **Detail:** `drive_index` took each drive's maximum capacity and latest model over its
  whole life, and both become snapshot features. On 2018-02-25 alone the panel reports a
  rounded capacity for all 98,321 live drives (4,000,790,000,000 instead of
  4,000,787,030,016 for a 4 TB drive), so the maximum marked every drive still alive on
  that day. For a train snapshot before that date, `capacity_tb` told the model the drive
  would survive until then. 100,258 drives had a capacity that varied at all, mostly this
  rounding; 12 more briefly reported 2^37 bytes, always after their true value. 7 drives
  change model string mid-life. The invariance test missed it because it holds the cohort
  fixed. The second review found that a rounded maximum still depends on the future in
  principle, and that the 10 drives that never report a capacity got NULL; all 10 fail
  within days, so NULL marked them (10 train snapshots).
- **Fix:** model and capacity are the first ones a drive reports, capacity rounded to 10
  GB. 94,816 drives report -1 on their first day only, so a first-day snapshot takes the
  next day's capacity: a nameplate fact the operator knows at install. Drives that never
  report one get their model's most common capacity. `drive_index` logs how many drives
  have a varying rounded capacity. `test_drive_metadata_does_not_see_the_future` runs
  `drive_index` on panels cut at two dates; the synthetic panel has a rounded-capacity
  day, a capacity that grows and a model rename after the cuts, -1 on first days and a
  drive that never reports a capacity. It fails on both earlier versions of the code.

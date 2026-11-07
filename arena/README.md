# Block arena

An experiment on the `rocm-engines` branch: many models compete on one dev split, one full
run at a time, on an AMD RX 7800 XT (16 GiB, ROCm 7.2) and a Ryzen 7 5700X (8 cores, 16
threads) with 31 GiB of RAM.

A block is one idea for predicting drive failure. It can use any engine, and it does not have
to be large. "We went big. What if we went small?" is a fair question to answer.

## The dev split

| Part | Drives (hash bucket) | Period | Used for |
|---|---|---|---|
| `train` | 0-44 | through 2022 | learning |
| `stop` | half of 45-54 | through 2022 | early stopping, model choice |
| `cal` | other half of 45-54 | through 2022 | calibration, by the harness only |
| `score` | 55-79 | 2023 | ranking, by the harness only |

Labels stop at 2022-12-31 for the first three parts and at 2023-12-31 for `score`. The real
test drives (buckets 80-99) and all of 2024-2025 are not in this data. Finalists are retrained
on the real split at the end and scored on test once.

The `score` year is later than anything a block trains on, so a block must cope with drift.
The mix of drives changes over time: large drives become common.

## The contract

Write `blocks/<name>/block.py`. Other files may sit next to it; the folder is on `sys.path`.

```python
def prepare(data, model_dir):          # optional, not timed
    """Load and shape the data: sort, bin, expand, move to the GPU. Returns a state object.
    No learning here: nothing that fits a model or optimizes a loss."""

def fit(data, model_dir, deadline, state):
    """Timed. Train and save everything predict needs to model_dir. `deadline` is a
    time.time() value: finish and save before it."""

def load(model_dir):
    """Load what fit saved, and return it. Not timed."""

def predict(model, X, hist):
    """Not timed. Called on shuffled batches of 100,000 rows. Returns raw scores:
    (n, 7) float logits of the hazard in each survival bin, or (n,) logits of
    "fails within 30 days". Higher means riskier. Must be finite."""
```

`data` is an `arena/api.py:FitData`:

- `data.train` and `data.stop`, each with `X` (float32, rows by 65 features), `hist` (float16,
  rows by 19 lags by 20 columns) and `meta` (`serial_number`, `date`, `duration_days`, `event`,
  `weight`). `X` and `hist` are memory-mapped.
- `data.features`, `data.categorical`, `data.groups`, `data.bin_edges`, `data.lags`,
  `data.hist_columns`.

`hist[i, j, c]` is column `c` of that drive `lags[j]` days before row `i`, as signed log1p. It
is NaN when the drive has no row that old. Lag 0 is the row itself. Features are in `X` as raw
values, with NaN for missing.

Survival bins: `bin_edges = [0, 7, 14, 30, 60, 90, 180, 365]`, so 7 bins. `steps/survival.py`
has the conventions: `expand` turns rows into per-bin training rows and handles censoring, and
`known_status` gives the status at a horizon. A censored row is not a healthy row.

Weights are inverse sampling probabilities. `weight` differs a lot between rows, and training
on `weight ** 0.5` ranks better than on `weight`.

## How a block is scored

1. The harness runs `predict` on `cal` rows and fits a Platt calibration per bin with the true
   weights. The same code calibrates every block, so a block does not calibrate itself.
2. It runs `predict` on `score` rows and turns the result into P(fail within 30, 60, 90 days).
3. Rank: weighted PR-AUC at 30 days. If the board goes stale, the coordinator moves the
   horizon 30 days further.
4. Every result is paired against `baseline_lgbm` with a drive-level bootstrap. An interval
   that holds zero is a tie.

Also reported: ROC-AUC, recall at a 1% false-alarm budget, observed over expected failures,
Brier skill, time, RAM, VRAM and GPU use.

## Limits

| | Full run | Smoke test |
|---|---|---|
| `fit` time | 20 minutes | 4 minutes |
| CPU threads | 14 (cores 0-13) | 2 (cores 14-15) |
| RAM | 26 GiB | 5 GiB |
| VRAM | 13.5 GiB | 1.5 GiB |
| Data | about 4M train rows | 3% of the drives |
| Who runs it | coordinator only | any agent |

`HDA_THREADS` holds the thread count: use it. A fit past its deadline by more than 60 seconds
is killed and gets no score. Loading, `prepare`, `predict` and scoring do not count against the
limit. A block that is truly impressive can earn a bigger budget from the coordinator.

## Rules for block agents

1. Work only in `blocks/<your block>/`, in your own git worktree. Never edit `arena/`, `steps/`,
   `config/`, `pipeline*.toml` or another block.
2. Python is `/home/lazy/Projects/hard-drive-analysis-v3/.venv/bin/python`. Never run `uv`,
   `pip` or the pipeline, and do not create a virtual environment. Need a package or a compiled
   engine? Ask in your report.
3. Test with `<python> arena/run.py <block> --smoke`, from your worktree. Smoke tests run one
   at a time and wait for each other. Do not run anything else heavy: no training or GPU work
   outside a smoke test, because a timed run may be going on.
4. Never read `build/dev/views/heldout`, `build/dev/views/smoke/heldout` or `dataset/`, and
   never read `results/full-*`, `build/` or the metrics of the real test split to tune your
   block.
5. `predict` must score each row on its own, from `X` and `hist`. No state between batches, no
   statistics of the batch, no attempt to link rows. Which rows exist and how they are spaced
   is a label leak: every day is kept just before a failure.
6. Do not use `date` or row spacing as a feature. `predict` does not get them for a reason.
   Using `date` to weight training rows, or to pick validation folds, is fine.
7. Deterministic seeds. Handle `deadline`: stop early and save, rather than be killed.
8. Commit your block on your branch when the smoke test passes, and report what you built.

# hard-drive-analysis-v3

A data science project built on top of Backblaze's dataset to study the impacts from `smartctl` in predicting hard drive failures.
Pipeline described in `pipeline.toml`. It runs each code block sequentially in a new subprocess, checkpoints all steps and uses cache when nothing changes.

## Commands
- Setup: `uv sync` (needs the `data-pipeline` repo checked out at `../data-pipeline`)
- Dry run: `uv run data-pipeline -n`
- Actual run: `uv run data-pipeline`
- Lint: `uv run ruff check steps tests`
- Tests: `uv run pytest -q`

CI (`.github/workflows/test.yml`) runs the lint and the tests on every push and pull request.

Note: To configure the size of the run, see `config/sample.toml`. Use `small` mode by default and `full` to get real results. `medium` sits in between.

## Conventions
- Any text should be primarily written in English, so that the `unslop` skill can operate properly. Any text in another language is just a translation or has passed through an **insane** amount of reviews.
- The one text of that kind is `article/main-article.md`, the FATEC technical report in Portuguese. It has already been through extensive rewrites and verification. Edit it only when asked, change only what was asked, and follow `article/ARTICLE.md` and `article/writing-guide.md`. Don't run `unslop` on it.
- Use the skill `unslop` to write documentation and research papers.
- Don't modify or add code, unless it's necessary.
- Every issue must be reported in the github repo of your current working branch.

## Talking to the user
- Be direct.
- Avoid chains with complex terms (if unavoidable, break it down).
- Avoid excessive compliments and flattery.
- When there is a contradiction in the instructions, ask the user for clarification.

## Layout
- `steps`: pipeline code, one module per group of steps.
- `tests`: pytest suite.
- `config/study.toml`: rules shared by every scale.
- `config/sample.toml`: run scale (`small`, `medium`, `full`).
- `dataset/dataset.parquet`: input panel (gitignored, checked by sha256 in `pipeline.toml`).
- `build`: stores last run's data.
- `build/report`: stores the final scores of the last run.
- `docs`: general documentation, besides `README.md`.
- `docs/audit`: reviews and suggestions from other agents (gitignored, may not exist).
- `article`: main theoretical study of the project. `main-article.md` is the report; `ARTICLE.md` and `writing-guide.md` are its writing rules.
- `article/research`: local copies of the reference papers cited by the article (gitignored, see `article/references.md`).
- `results`: small artifacts of past full-scale runs, copied from `build`.

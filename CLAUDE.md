# hard-drive-analysis-v3

Data science project built on top of BackBlaze's dataset to study the impacts from `smartctl` in predicting hard drive failures.
Pipeline described in `pipeline.toml`. It checkpoints all steps.

## Commands
- Setup: `uv sync`
- Dry run: `uv run data-pipeline -n`
- Actual run: `uv run data-pipeline`

## Layout
- `build`: stores last run's data.
- `build/report`: stores the final scores of the last run.
- `audit`: reviews and suggestions from other agents.
- `docs`: general documentation, besides `README.md`.
- `article`: main theoretical study of the project.
- `article/research`: local copies of the reference papers cited by the article (gitignored, see `article/references.md`).
- `results`: small artifacts of past full-scale runs, copied from `build`.
- `research_notes`, `reports`: literature research behind the methodology.
- `info`: hardware report of the machine used for full-scale runs.

## Conventions
- Do not read from other projects at `projects/`.
- Use the skill `unslop` to write documentation.
- Don't modify or add code, unless it's necessary.

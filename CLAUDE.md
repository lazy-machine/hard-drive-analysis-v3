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
- `article/reseach`: stores reference paper and articles for the main article.

## Conventions
- Do not read from other projects at `projects/`.
- Use the skill `unslop` to write documentation.
- Don't modify or add code, unless it's necessary.

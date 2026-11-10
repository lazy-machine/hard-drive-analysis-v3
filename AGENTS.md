# hard-drive-analysis-v3

Data science project built on top of BackBlaze's dataset to study the impacts from `smartctl` in predicting hard drive failures.
Pipeline described in `pipeline.toml`. It runs each code block sequentially in a new subprocess, checkpoints all steps and uses cache when nothing changes.

## Commands
- Setup: `uv sync`
- Dry run: `uv run data-pipeline -n`
- Actual run: `uv run data-pipeline`

Note: To configure the size of the run, see `config/sample.toml`. Use `small` mode by default and `full` to get real results.

## Conventions
- Any text should be primarily written in English, so that the `unslop` skill can operate properly. Any text in another language is just a translation or has passed through an **insane** amount of reviews
- Use the skill `unslop` to write documentation and research papers.
- Don't modify or add code, unless it's necessary.
- Every issue must be report in the github repo of your current working branch.

## Talking to the user
- Be direct.
- Avoid chains with complex terms (if unavoidable, break it down).
- Avoid excessive compliments and flattery.
- When there is a contradiction in the instructions, ask the user for clarification.

## Layout
- `build`: stores last run's data.
- `build/report`: stores the final scores of the last run.
- `docs`: general documentation, besides `README.md`.
- `docs/audit`: reviews and suggestions from other agents.
- `article`: main theoretical study of the project.
- `article/research`: local copies of the reference papers cited by the article (gitignored, see `article/references.md`).
- `results`: small artifacts of past full-scale runs, copied from `build`.

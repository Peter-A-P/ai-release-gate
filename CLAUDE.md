# Working notes for Claude Code

This repository is the AI Release Gate: a frozen-suite, monthly record of language-model
drift (phase 1, planned in [PLAN.md](PLAN.md)) and, from December 2026, a statistically
honest release gate for prompt and model changes (phase 2).

## Read first

- [README.md](README.md): what this is and the current result table.
- [PLAN.md](PLAN.md): the full design for the drift runs. Do not deviate from it silently;
  if something in it turns out wrong, change the plan in the same commit as the code and
  say why in the commit message.

## Engineering standard

- Python 3.13. Typed throughout; `mypy --strict` and `ruff` clean in CI.
- Tests that fail meaningfully. Every grader has fixtures including adversarial outputs
  (markdown fences, trailing chatter, unicode digits, empty strings).
- `pyproject.toml` with pinned major versions and a comment saying why for each pin.
- Docs ship in the same commit as the change.
- Never commit credentials, raw vendor keys, or anything from `.env`.

## Rules specific to this repository

- **The suite is frozen.** Files under `drift/suite/v1/` are never edited after
  `SUITE_HASH` is committed. A change means a new suite version and a bridging month.
- **The record is append-only.** Never rewrite or delete anything under `drift/runs/`.
  A bad run is marked, not removed.
- **No caching on the monthly run.** Development caching is fine for building graders;
  the scheduled job must hit the vendors.
- **No LLM grading in Part A.** Programmatic graders only. In Part B a judge is used only
  after calibration against the gold set, and its kappa is stored with every run.
- **The ledger is append-only.** A mistaken run record is superseded by a new record that
  references it, never edited.
- **Every reported score carries a confidence interval.** A bare percentage is a bug.
- **Plain punctuation** in everything written here: no em-dashes or other typographic
  dashes, straight quotes only.

## What goes in the README

The README opens with the one-liner, the results table, and the honest limitation, before
any installation instructions. The monthly job updates the table; do not hand-edit it.
Record one approach that was tried and rejected, with the evidence, once the dry runs
have produced it.

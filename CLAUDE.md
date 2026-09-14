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

- Python 3.13. Typed throughout; `mypy` and `ruff` clean in CI.
- **Run the four commands CI runs, not shorter versions of them**, in this order:
  `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest`.
  Bare `mypy` is not the same check as `mypy --strict drift`: `[tool.mypy]` in
  `pyproject.toml` sets `files = ["drift", "tests"]`, so the bare command covers the tests
  and the narrower one does not. Three commits went red on 2026-09-14 on exactly that gap,
  over an unused `type: ignore` in a test, and nobody noticed for eight hours.
- Tests that fail meaningfully. Every grader has fixtures including adversarial outputs
  (markdown fences, trailing chatter, unicode digits, empty strings).
- `pyproject.toml` with pinned major versions and a comment saying why for each pin.
- Docs ship in the same commit as the change.
- Never commit credentials, raw vendor keys, or anything from `.env`.

## Rules specific to this repository

- **The suite is frozen.** Files under `drift/suite/v1/` are never edited after
  `SUITE_HASH` is committed. A change means a new suite version and a bridging month.
- **The record is append-only as it is written.** Nothing under `drift/runs/` is deleted,
  the runner only ever appends, and a bad run is marked in `RUN.json` rather than removed.
- **A grade is the one field a fix may rewrite, and only through `drift replay --write`.**
  Correcting a grader means correcting it across every month, or a later month is being
  compared against an earlier one on a different yardstick, which is the confound this whole
  project exists to remove. So: fix the grader, run `uv run drift replay --write --month X`
  for **every** month, then `drift collect`. Nothing is lost, because git holds every
  previous state and the commit says what changed.
  - Every record carries `graded_by`, the hash of the grader sources behind its grade
    (`drift.graders.GRADERS_HASH`), and a report names its generation and refuses to be
    quiet when a month holds more than one. Held-out records keep their run-time grade and
    stamp, because their text was never stored and they cannot be regraded.
  - Run-time grading and replay grading are **one function**, `drift/runner/grading.py`.
    Never grade anywhere else. Before it existed the two disagreed, and the replay path
    knew neither that a vendor-level refusal counts as a refusal nor that a truncated
    answer is ungradeable rather than wrong.
- **No caching on the monthly run.** Development caching is fine for building graders;
  the scheduled job must hit the vendors.
- **No LLM grading in Part A.** Programmatic graders only. In Part B a judge is used only
  after calibration against the gold set, and its kappa is stored with every run.
- **The ledger is append-only.** A mistaken run record is superseded by a new record that
  references it, never edited.
- **Every reported score carries a confidence interval.** A bare percentage is a bug.
- **The refusal classifier is measured by hand every month it is quoted**, with
  `drift refusal label --month X` (blind, one keypress, resumable, about 35 minutes for the
  ~76 answers it asks for) and `drift refusal rate`. The report generates the section from
  the label file, so a month without labels says so in print rather than passing the
  classifier off as exact.
  - **A human reading is the most expensive thing in this project and must survive a code
    change.** The judgement is the durable fact; the classifier's verdict is recomputed, not
    remembered, and anything already labelled stays in the queue wherever it later falls.
  - **Never tune the classifier to make an arm look better.** Its known unfixable failure is
    a model answering a harmless reading of an ambiguous request using no refusing language
    at all. That is published as a limitation. A classifier tuned until every vendor looks
    safe measures nothing, and `tests/test_graders.py` holds a case that fails if anyone
    tries.
- **Plain punctuation** in everything written here: no em-dashes or other typographic
  dashes, straight quotes only.

## What goes in the README

The README opens with the one-liner, the results table, and the honest limitation, before
any installation instructions. The monthly job updates the table; do not hand-edit it.
Record one approach that was tried and rejected, with the evidence, once the dry runs
have produced it.

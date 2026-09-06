# AI Release Gate

No prompt or model change reaches users unless it is proven not to have regressed: the
discipline a test suite gives code, applied to AI, with an audit trail a regulator can
read. Plus a public, month-by-month record of how the major vendors' "frozen" models
silently change, on a fixed suite, with error bars.

**Status: planning.** Nothing has run yet. Both phases are planned in [PLAN.md](PLAN.md):
Part A, the monthly drift record, with the first official run targeted for 2026-09-27; Part
B, the release gate itself, built Dec 2026 to Jan 2027.

## Result

Not yet measured. This table is filled by the monthly job from the first run onward.

| Model (arm) | Run | Accuracy (95% CI) | Flip rate vs previous | Same-day flip rate | Refusal rate | Drift? |
|---|---|---|---|---|---|---|
| _none yet_ | | | | | | |

## What this does not do

- It does not judge open-ended quality in phase 1. Every drift item is graded by a
  program, not by another model, so that the judge cannot drift too.
- It does not run frontier-tier models monthly. Cost.
- It does not explain why a vendor changed a model. It shows that and when.

## How it works

See [PLAN.md](PLAN.md). Part A: a frozen suite of about 420 programmatically graded
items, run monthly against a dated snapshot and a floating alias from each vendor plus an
open-weights control, five repeats per item so month-to-month change is tested against a
same-day noise floor, raw responses committed, numbers reproducible offline. Part B: a
judge calibrated against human labels and corrected for its own error, paired
non-inferiority tests with bootstrap intervals, a power function from the model-selection
project, a GitHub Action that blocks a regression on a real repository, four red-team
suites, an append-only ledger, and a dashboard at gate.peterparker.ca.

## Part of a portfolio

One of ten projects built over twelve months. This one is the measurement layer for the
others: the compliant gateway, the filings analyst, the small-model cost frontier and the
self-healing production AI all use it to make their claims.

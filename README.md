# AI Release Gate

No prompt or model change reaches users unless it is proven not to have regressed: the
discipline a test suite gives code, applied to AI, with an audit trail a regulator can
read. Plus a public, month-by-month record of how the major vendors' "frozen" models
silently change, on a fixed suite, with error bars.

**Status: Part A runner built; 330 of the 420 suite items in place: 270 drawn from public
sets on 2026-09-10 ([how](docs/sampling.md)) and 60 generated on 2026-09-11 (20 long-context
recall passages and 40 paraphrases, [how](docs/long-context.md)); the 90 hand-written items
in progress; first run targeted 2026-09-27.** Both phases are planned in [PLAN.md](PLAN.md):
Part A, the monthly drift record, with the first official run targeted for 2026-09-27; Part
B, the release gate itself, built Dec 2026 to Jan 2027.

## Result

Not yet measured. This table is filled by the monthly job from the first run onward.

| Run | Arm | Accuracy (95% CI) | Same-day flip rate (noise floor) | Flip rate vs previous run | Refused when it should answer | Cost per 1,000 calls |
|---|---|---|---|---|---|---|
<!-- drift:start -->
| _none yet_ | | | | | | |
<!-- drift:end -->

The monthly job writes the rows between the markers; the full report per month, with the
drift call against the noise floor and the control arm, is under `drift/reports/`.

## What this does not do

- It does not judge open-ended quality in phase 1. Every drift item is graded by a
  program, not by another model, so that the judge cannot drift too.
- It does not run frontier-tier models monthly. Cost.
- It does not explain why a vendor changed a model. It shows that and when.

## How it works

See [PLAN.md](PLAN.md). Part A: a frozen suite of about 420 programmatically graded
items, run monthly against a dated snapshot and a floating alias from each vendor (plus a
second, snapshot-only Anthropic arm, because that vendor's newer ids have no alias) and an
open-weights control, five repeats per item so month-to-month change is tested against a
same-day noise floor, raw responses committed, numbers reproducible offline. Part B: a
judge calibrated against human labels and corrected for its own error, paired
non-inferiority tests with bootstrap intervals, a power function from the model-selection
project, a GitHub Action that blocks a regression on a real repository, four red-team
suites, an append-only ledger, and a dashboard at gate.peterparker.ca.

## Part of a portfolio

One of fifteen projects built over twelve months. This one is the measurement layer for the
others: the compliant gateway, the filings analyst, the small-model cost frontier and the
self-healing production AI all use it to make their claims.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's. AI coding
assistants (Claude Code) were used for implementation and drafting, the way a senior
engineer uses them in 2026. Every number in the results table is reproducible from this
repository with one command, and that reproducibility is the evidence that matters.

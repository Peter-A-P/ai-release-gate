# AI Release Gate

No prompt or model change reaches users unless it is proven not to have regressed: the
discipline a test suite gives code, applied to AI, with an audit trail a regulator can
read. Plus a public, month-by-month record of how the major vendors' "frozen" models
silently change, on a fixed suite, with error bars.

**Status: the record has started.** The suite is frozen at v1, hash `72f780dfb525d84d`: 420
items, of which 270 were drawn from public sets on 2026-09-10 ([how](docs/sampling.md)), 60
were generated on 2026-09-11 (20 long-context recall passages and 40 paraphrases,
[how](docs/long-context.md)) and 90 were written by hand ([how](docs/writing-items.md)).
Twenty are held out, committed as hashes only. The panel of eight arms was chosen from the
vendors' own published model lists on 2026-09-12 and dated. **The first official run
completed on 2026-09-13: 16,800 calls for US$19.53.** Both phases are planned in
[PLAN.md](PLAN.md): Part A, the monthly drift record, running now; Part B, the release gate
itself, built Dec 2026 to Jan 2027.

## Result

The first run, 2026-09-13. Eight arms, 420 frozen items, five repeats each. A second full run
followed on 2026-09-16, four days later, to measure what moves between two runs when nothing
has had time to change.

**The column to read first is the same-day flip rate.** It is how much a score moves when
nothing has changed at all: the same question, to the same model, five times in one sitting.
It runs from 0.2% to 5.0% depending on the arm. Every later claim that a model drifted has to
clear its own arm's floor before it counts, which is the whole reason this record exists.

**The between-run baseline, measured 2026-09-16.** The same suite and the same arms, run again
four days later. Four days is too short for a vendor to change a model, so anything above the
noise floor here would be this method failing rather than a model moving. Nothing was:

| | Between-run flip rate, 2026-09-13 to 2026-09-16 |
|---|---|
| Lowest arm | 0.2% (anthropic-sonnet-snapshot) |
| Highest arm | 2.9% (openai-alias) |
| Pinned open-weights control | 1.9% |
| Arms where drift was declared | none, 0 of 8 |

Every arm came in at or below its own same-day floor, every McNemar p was non-significant, and
the accuracy change ran from -1.2% to +0.5%. So **a score moves by up to about 3% between two
runs with nothing changed at all**, and a monthly figure has to clear that before it means
anything. The full table is in [the second run's report](drift/reports/2026-09-run2.md).

The two runs cost US$19.53 and US$19.57 against an expected US$20.35 each.

One caveat belongs beside the table rather than below it. The refusal figures come from a
classifier that is eleven regular expressions, and its own error rate is measured by hand
against these same stored answers, blind, without being shown what the classifier decided.
It has now been measured twice, on two separate runs: **5.7% (5.3% to 8.0%)** from 76 answers
read on 2026-09-13, and **5.6% (5.2% to 8.1%)** from 72 read on 2026-09-17. Two independent
passes agreeing to a tenth of a point is the reason to believe the number.

Every error ran the same way in both passes: the classifier missed refusals and scored them as
compliance, and never once called a compliance a refusal. That flatters nobody and understates
every vendor, so the refusal columns are a floor rather than an estimate. What it cannot be
fixed to catch is set out in [the month's report](drift/reports/2026-09.md), and it is the more
interesting half.

| Run | Arm | Accuracy (95% CI) | Same-day flip rate (noise floor) | Flip rate vs previous run | Refused when it should answer | Cost per 1,000 calls |
|---|---|---|---|---|---|---|
<!-- drift:start -->
| 2026-09 | anthropic-alias | 95.0% (92.9% to 96.9%, n = 420) | 0.5% (0.0% to 1.2%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$1.33 |
| 2026-09 | anthropic-snapshot | 95.0% (92.9% to 96.9%, n = 420) | 0.2% (0.0% to 0.7%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$1.33 |
| 2026-09 | anthropic-sonnet-snapshot | 97.6% (96.0% to 98.8%, n = 420) | 1.4% (0.5% to 2.6%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$2.78 |
| 2026-09 | google-alias | 97.4% (95.7% to 98.8%, n = 420) | 4.0% (2.4% to 6.0%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$1.16 |
| 2026-09 | google-snapshot | 96.9% (95.0% to 98.3%, n = 420) | 5.0% (3.1% to 7.4%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$1.13 |
| 2026-09 | openai-alias | 94.5% (92.4% to 96.7%, n = 420) | 4.0% (2.4% to 6.2%, n = 420) | first month | 3.0% (0.0% to 7.0%, n = 100) | US$0.49 |
| 2026-09 | openai-snapshot | 94.8% (92.6% to 96.9%, n = 420) | 1.0% (0.2% to 2.1%, n = 420) | first month | 5.0% (1.0% to 10.0%, n = 100) | US$0.49 |
| 2026-09 | openweights-control | 92.1% (89.5% to 94.5%, n = 420) | 3.6% (1.9% to 5.5%, n = 420) | first month | 0.0% (0.0% to 0.0%, n = 100) | US$0.60 |
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

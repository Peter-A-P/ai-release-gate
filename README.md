# AI Release Gate

> No prompt or model change reaches users unless it is proven not to have regressed: the
> discipline a test suite gives code, applied to AI, with an audit trail a regulator can read.
> Plus a public, month-by-month record of how the major vendors' "frozen" models silently
> change, on a fixed test, with error bars.

Software teams protect themselves with automated tests: change the code, run the tests, and you
find out straight away whether you broke something. Teams building on AI models have no
equivalent, for two reasons. The model is not theirs, and it can change underneath them without
notice. And the test itself is unreliable, because an AI model asked the identical question
twice does not reliably give the identical answer.

This project fixes the second problem so that the first one can be measured, and publishes the
evidence month by month while it does.

**Status:** the record has started. Two full runs are in, on 2026-09-13 and 2026-09-16. The
headline number, how much a score moves when nothing has changed, is measured and published
below. The twelve-month record runs to September 2027.

---

## The argument this settles

Every team shipping AI has the same meeting. Somebody changes a prompt, or the vendor ships a
new model version, and the evaluation score moves from 86 to 83. Is that a regression, or is it
nothing? The meeting goes in circles, because nobody in the room can answer it.

It cannot be answered, because **three points of movement is roughly what you get from changing
nothing at all.**

There is a second version of the same problem, one level up. When you call a vendor's model by a
pinned, dated name, that date is a promise that the thing behind it does not change. Teams keep
reporting that behaviour shifts anyway: something that worked in March stops working in June.
Nobody can prove it, because proving it would mean having run the same fixed test every month
since before the shift. That record does not exist in public, and it cannot be made after the
fact. Either somebody was measuring all along, or the evidence is gone.

This project is somebody measuring all along.

## Why you cannot just run the test twice

The obvious approach is to run your questions today, run them again next month, and see what
changed. It does not work, because several different things move that number and only one of
them is the thing you care about:

| Why a score moved | Is it a real change? | How you would tell |
|---|---|---|
| The model's own randomness, call to call | No | Ask the same model the same question several times in one sitting |
| The serving stack: hardware, routing, load | No | Run a model whose weights physically cannot change, as a control |
| The vendor quietly changed the model behind a pinned name | **Yes** | Measure both floors above first, on a test that never changes |
| A prompt or model your team deliberately changed | **Yes, and this is the one you meant to measure** | All of the above, then a paired test with error bars |

The first three rows are why most AI evaluation is not trustworthy. The last row is what a
release gate is for.

So the first thing this project measures is not drift. It is **the noise floor**: how far the
score moves when nothing whatsoever has changed. Every later claim that a model drifted has to
clear that floor before it counts.

## Results

Every run asks the same 420 frozen questions of 8 model configurations, 5 times each. That is
16,800 calls per run, about US$20. Nothing is graded by another AI: every answer is marked by an
ordinary program, so the marker cannot drift either.

**How to read the table.** Each row is one model configuration in one run.

- **Model configuration** is a specific way of calling one model. A `snapshot` is a dated,
  pinned version the vendor promises is frozen. An `alias` is a floating name like "latest",
  which the vendor is free to repoint at any time. Running both, side by side, is how you catch
  a vendor moving a model that was supposed to be still. `openweights-control` is an
  open-weights model with fixed weights running on fixed hardware: it physically cannot change,
  so whatever it appears to do is the measurement's own noise and nothing else.
- **Accuracy** is the share of the 420 questions answered correctly.
- **Noise floor (same-day)** is the headline. The share of questions where the model gave a
  different result across its own 5 tries **in the same sitting, with nothing changed**. This is
  the bar every drift claim must clear.
- **Change vs previous run** compares this run against the one before it, question by question.
- **Wrongly refused** is how often a model declined a perfectly reasonable request.
- Every figure carries a **95% confidence interval** in brackets: the range the true value is
  very likely to sit in. A number without one is meaningless at this sample size, so none are
  published without one.

<!-- drift:start -->

| Run | Model configuration | Accuracy | Noise floor (same-day) | Change vs previous run | Wrongly refused | Cost / 1,000 calls |
|---|---|---|---|---|---|---|
| 2026-09 | anthropic-alias | 95.0% (92.9 to 96.9) | 0.5% (0.0 to 1.2) | first run | 0.0% (0.0 to 0.0) | US$1.33 |
| 2026-09 | anthropic-snapshot | 95.0% (92.9 to 96.9) | 0.2% (0.0 to 0.7) | first run | 0.0% (0.0 to 0.0) | US$1.33 |
| 2026-09 | anthropic-sonnet-snapshot | 97.6% (96.0 to 98.8) | 1.4% (0.5 to 2.6) | first run | 0.0% (0.0 to 0.0) | US$2.78 |
| 2026-09 | google-alias | 97.4% (95.7 to 98.8) | 4.0% (2.4 to 6.0) | first run | 0.0% (0.0 to 0.0) | US$1.16 |
| 2026-09 | google-snapshot | 96.9% (95.0 to 98.3) | 5.0% (3.1 to 7.4) | first run | 0.0% (0.0 to 0.0) | US$1.13 |
| 2026-09 | openai-alias | 94.5% (92.4 to 96.7) | 4.0% (2.4 to 6.2) | first run | 3.0% (0.0 to 7.0) | US$0.49 |
| 2026-09 | openai-snapshot | 94.8% (92.6 to 96.9) | 1.0% (0.2 to 2.1) | first run | 5.0% (1.0 to 10.0) | US$0.49 |
| 2026-09 | openweights-control | 92.1% (89.5 to 94.5) | 3.6% (1.9 to 5.5) | first run | 0.0% (0.0 to 0.0) | US$0.60 |

<!-- drift:end -->

Intervals are 95% bootstrap intervals. Accuracy and flip rates are over n = 420 questions, the
refusal column over n = 100.

**The noise floor runs from 0.2% to 5.0% depending on the model configuration.** That spread is
itself the point: a 2% change means nothing on a Google arm and would be remarkable on an
Anthropic snapshot. A single global threshold would be wrong for almost every arm.

### The between-run baseline, measured 2026-09-16

The same suite and the same models, run again four days later. Four days is too short for any
vendor to change a model, so anything above the noise floor here would be **this method failing**
rather than a model moving. Nothing was:

| | Between-run change, 2026-09-13 to 2026-09-16 |
|---|---|
| Lowest configuration | 0.2% (`anthropic-sonnet-snapshot`) |
| Highest configuration | 2.9% (`openai-alias`) |
| Open-weights control | 1.9% |
| Configurations where drift was declared | **none, 0 of 8** |

Every arm came in at or below its own same-day floor, every statistical test was
non-significant, and accuracy moved between -1.2% and +0.5%. So: **a score moves by up to about
3% between two runs with nothing changed at all.** That is the anchor for the next twelve
months, and it is the number the project exists to produce.

The two runs cost US$19.53 and US$19.57 against an expected US$20.35 each. Full per-run detail,
including the drift call against the noise floor and the control, is in
[`drift/reports/`](drift/reports/).

## The honest limitation

One caveat belongs beside the table rather than buried below it.

Deciding whether a model *refused* a request is done by a classifier built from eleven regular
expressions, and a regular expression is a crude instrument for reading English. So its error
rate is measured by hand: a human reads the stored answers blind, without being shown what the
classifier decided, and the two are compared.

It has now been measured twice, on two separate runs: **5.7% (5.3% to 8.0%)** from 76 answers
read on 2026-09-13, and **5.6% (5.2% to 8.1%)** from 72 read on 2026-09-17. Two independent
passes agreeing to a tenth of a point is the reason to believe the number rather than the first
draw being lucky.

Every error ran the same way in both passes: the classifier missed refusals and scored them as
compliance, and never once called a compliance a refusal. That flatters nobody and understates
every vendor, so **the refusal columns are a floor, not an estimate.**

The part that cannot be fixed is the more interesting half, and it is set out in
[the month's report](drift/reports/2026-09.md): a model answering a harmless reading of an
ambiguous request, using no refusing language at all, is indistinguishable by any regular
expression from a model that simply complied. Tuning the classifier until that case disappears
would mean tuning until every vendor looks safe, which measures nothing. It is published as a
limitation instead, and a test in the suite fails if anyone tries.

## What this deliberately does not do

- **It does not use an AI to grade an AI**, in the drift record. Every answer is marked by a
  plain program, so that the marker cannot drift while it is measuring drift.
- **It does not run the largest, most expensive models every month.** Cost.
- **It does not explain why a vendor changed a model.** It shows that one did, and when.
- **It does not claim drift it cannot separate from noise.** That is the whole discipline.

## How it works

The suite is **frozen**: 420 questions, content-hashed at `72f780dfb525d84d`, never edited after
the hash is committed. Changing a question would mean comparing next month against last month on
a different test, which is exactly the confound the project exists to remove. **20 questions are
held out** and never published, so a vendor cannot train on them; only their hashes are in this
repository.

Eight arms cover a dated snapshot and a floating alias from each of Anthropic, OpenAI and Google,
a second Anthropic snapshot, and the pinned open-weights control. Every question is asked 5
times per run, which is what produces the same-day noise floor.

The record is **append-only**. Raw responses are committed, so every published number can be
regenerated offline without spending a cent, and a bad run is marked rather than deleted. A
single grading function serves both live runs and re-grades, because when they were two
functions they disagreed. Every record is stamped with a hash of the grader that produced it, and
a report refuses to stay quiet if a month contains more than one.

Part B, building December 2026 to January 2027, turns this into the gate itself: a judge
calibrated against human labels and corrected for its own error rate, paired non-inferiority
tests, a power analysis, and a GitHub Action that blocks a regression on a real repository with a
measured false-block rate.

Full design in [PLAN.md](PLAN.md).

## Reproduce every number yourself

No vendor key and no spending is needed. The raw responses are in the repository.

```bash
uv sync
uv run drift replay --month 2026-09     # re-grade every stored answer
uv run drift report --month 2026-09     # rebuild the published report
```

`replay` regrades all 15,993 stored answers and, at the last check, disagreed with the recorded
grade zero times and produced a report byte-for-byte identical to the committed one.

## Part of a portfolio

One of fifteen projects built over twelve months. This one is the measurement layer for the
others: the compliant gateway, the filings analyst, the small-model cost frontier and the
self-healing production AI all use it to make their claims. Its statistical core comes from the
model-selection project, which supplies the power analysis and item calibration.

## How this was built

Design, methodology, evaluation choices and judgement are Peter Parker's. AI coding assistants
(Claude Code) were used for implementation and drafting, the way a senior engineer uses them in
2026. Every number in the results table is reproducible from this repository with one command,
and that reproducibility is the evidence that matters.

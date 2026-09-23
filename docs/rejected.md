# What was tried and rejected: one call per item

Every project in this portfolio has to name an approach it tried and abandoned, and show the
evidence that killed it. This is that document for the drift record.

The rejected approach is **k = 1: call each question once per run instead of five times.**

## Why it was worth trying

Repeats are four fifths of the bill. The suite is 420 questions against 8 model
configurations. At five calls each that is 16,800 calls and about US$20 a run; at one call
each it is 3,360 calls and about US$4. Over the twelve months this record is meant to run,
that is the difference between roughly CA$320 and roughly CA$65.

The argument for it is better than the price. A single run at k = 1 reports almost exactly the
accuracy that five runs report:

| Model configuration | Accuracy at k = 5 | Accuracy from a single draw | Spread |
|---|---|---|---:|
| anthropic-alias | 95.0% | 95.0% to 95.2% | 0.2pp |
| anthropic-snapshot | 95.0% | 95.0% to 95.2% | 0.2pp |
| anthropic-sonnet-snapshot | 97.6% | 97.4% to 97.9% | 0.5pp |
| google-alias | 97.4% | 95.7% to 97.1% | 1.4pp |
| google-snapshot | 96.9% | 95.9% to 96.9% | 1.0pp |
| openai-alias | 94.5% | 94.3% to 95.2% | 1.0pp |
| openai-snapshot | 94.8% | 94.5% to 94.8% | 0.2pp |
| openweights-control | 92.1% | 91.4% to 92.6% | 1.2pp |

From the run of 2026-09-13, each arm reduced to one call per question in each of the five ways
that reduction can be made. The widest an arm's reported accuracy moves is 1.4 points, and
most move by a fifth of a point. Anyone looking only at this table would cut the repeats and
bank the money, and that is exactly the mistake.

## What it actually costs

Not the score. The floor.

This project declares drift when a model's between-run flip rate exceeds the upper bound of
its **same-day flip rate**: how often the model contradicts itself across its own repeats in
a single sitting, with nothing changed. That number is what makes a movement mean anything,
and it is measured, per arm, from the repeats. One call per question cannot produce it. There
is no second call on the same question to compare against.

So the floor does not get noisier under k = 1. It ceases to exist, and the failure lands on
whichever horn the team picks.

**Keep the rule, and the gate can never fire.** `drift_declared` refuses to declare drift
without a floor to clear, so a k = 1 record declares drift on 0 of 8 arms no matter how far a
model moves. The measurement is not degraded; it is over. This half is an argument rather
than a finding: it is true of any k = 1 record whatsoever, so it is reported but it is not
what the verdict turns on.

**Drop the rule, and the gate cries wolf.** With no floor, the only test left is whether the
change is distinguishable from zero. Applying that to two real runs four days apart, with the
same suite, the same arms, and nothing a vendor could possibly have shipped in between:

| Model configuration | Same-day floor at k = 5 | Between-run change | k = 5 declares drift | Same-day floor at k = 1 | Between-run change at k = 1, median draw | k = 1 declares drift |
|---|---|---|---|---|---|---|
| anthropic-alias | 2.4% (1.0 to 3.8) | 0.7% (0.0 to 1.7) | no | none, n = 0 | 1.4% (0.5 to 2.6) | 24 of 25 draws |
| anthropic-snapshot | 1.7% (0.5 to 3.1) | 0.7% (0.0 to 1.7) | no | none, n = 0 | 0.7% (0.0 to 1.7) | 9 of 25 draws |
| anthropic-sonnet-snapshot | 2.1% (1.0 to 3.6) | 0.2% (0.0 to 0.7) | no | none, n = 0 | 0.7% (0.0 to 1.7) | 10 of 25 draws |
| google-alias | 3.3% (1.7 to 5.0) | 1.7% (0.7 to 2.9) | no | none, n = 0 | 1.9% (0.7 to 3.3) | 25 of 25 draws |
| google-snapshot | 3.8% (2.1 to 5.7) | 1.2% (0.2 to 2.4) | no | none, n = 0 | 2.4% (1.0 to 4.0) | 25 of 25 draws |
| openai-alias | 3.6% (1.9 to 5.5) | 2.9% (1.4 to 4.5) | no | none, n = 0 | 2.6% (1.2 to 4.3) | 25 of 25 draws |
| openai-snapshot | 2.9% (1.4 to 4.8) | 1.4% (0.5 to 2.6) | no | none, n = 0 | 1.9% (0.7 to 3.3) | 25 of 25 draws |
| **openweights-control** | 4.0% (2.4 to 6.2) | 1.9% (0.7 to 3.3) | **no** | none, n = 0 | 1.9% (0.7 to 3.4) | **25 of 25 draws** |

All intervals are 95% bootstrap intervals over n = 420 questions, except where a draw landed
on an ungradeable call and the question dropped out of that draw. "25 draws" is every way of
choosing which single call to keep in each run: 5 in the first run times 5 in the second.

**Across all 25 pairings, k = 1 declares drift on 6 to 8 of the 8 arms. The published rule
declares it on none.** Which arms get flagged depends on nothing but which call you happened
to keep.

## The line that settles it

`openweights-control` is an open-weights model with fixed weights on fixed hardware. It cannot
drift. That is why it is in the panel.

**k = 1 declares that it drifted in 25 of 25 draws.** Not sometimes, not marginally: every
single way of reducing these two runs to one call per question produces a statistically
significant change in a model that physically could not have changed. The published rule
declares it in none of them.

A rule that fires on the control is not measuring the vendors. It is measuring itself.

## What this does not claim

It does not claim k = 1 gives a worse score, because it does not, as the first table shows.
It does not claim five repeats is the right number rather than three or ten; that is a
separate question the October run's power analysis addresses. And it does not claim the
finding would hold at any sample size: with 420 questions, a between-run flip rate around 2%
is roughly 8 questions, and the interval around it clears zero comfortably while sitting well
inside the same-day floor. That gap between "different from zero" and "different from noise"
is the whole of it.

## Reproduce it

No vendor is called and nothing is spent. Both runs are in this repository.

```bash
uv run drift rulec repeats --month 2026-09-run2 --baseline 2026-09
```

The analysis is [`drift/experiments/repeats.py`](../drift/experiments/repeats.py) and its
tests are [`tests/test_repeats_experiment.py`](../tests/test_repeats_experiment.py). The
verdict is computed from the counts rather than asserted: given a record where no draw
disagrees with another, the same code prints "Not rejected", and a test holds it to that.

## The other candidate: run, and not rejected

PLAN.md section 10 names a second approach expected to fail: **an LLM judge in place of the
programmatic graders**. The harness ([`drift/experiments/judge.py`](../drift/experiments/judge.py),
`drift rulec judge`) is built to reject the strongest form of the idea rather than a straw man:
the judge sees the reference answer, is asked for one word, runs at temperature 0, and is shown
identical stored text every time, so any disagreement it has with itself is a floor on the
approach's noise rather than a ceiling.

It ran on 2026-09-23 (the `rulec` workflow, runs 35839815033 and 35839909791), and **the
expectation was wrong.** `claude-haiku-4-5-20251001` judged 50 stored answers from the 2026-09
run, one per item, spread across all seven blocks, 5 times each: 250 calls, US$0.35.

| Measure | Value |
|---|---|
| Judge disagrees with itself across repeats | 0.0% (0.0% to 4.9%, n = 50) |
| Judge majority agrees with the programmatic grader | 98.0% (90.9% to 99.8%, n = 50) |
| Replies that were not the single word asked for | 0 of 250 |

Not one of the 50 items got two different verdicts in five tries. The upper bound, 4.9%, sits
under the 5% effect the suite is powered to detect, so on the test as designed the approach is
**not rejected**, and it is published as not rejected. Three things keep that from meaning more
than it says:

- **The margin is thin.** 4.9% against 5% is a Jeffreys interval; the more conservative exact
  (Clopper-Pearson) bound on 0 of 50 is 7.1%, which would have called it undecided. What 50
  items can say is that the judge does not waver often, not that it never does.
- **It measures one of the two ways a judge adds noise.** A judge disagreeing with itself on one
  day is the half this test can see. The other half is the judge's own vendor changing it between
  months, which is exactly what this project exists to detect in other models, and a same-day
  test is blind to it by construction. The programmatic graders cannot change at all, which is
  why the drift record keeps them.
- **The one error was a bias, not noise.** On `recall-1016` the stored answer was "The
  Kestrelmoor." against a reference rendered as "exactly: Kestrelmoor". The grader normalises the
  article and full stop and marks it right; the judge read "exactly" literally and marked it wrong,
  all five times. Repeating a judge finds its noise and never its biases: a judge that is wrong
  the same way every time scores perfectly on this test.

Reproduce offline with `uv run drift rulec judge --month 2026-09 --replay`. The first rendering
of this report printed the result under the heading "Rejected" with a self-disagreement of
"0.0% (0.0% to 0.0%)", which were the expectation and a collapsed bootstrap writing the result;
both are fixed and tested.

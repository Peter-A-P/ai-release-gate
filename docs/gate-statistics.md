# The gate's statistics

What the gate computes when it is asked whether a candidate may ship, and what the first
measurement of it against itself found. PLAN.md B2.2 and B5 are the design; this is the
implementation and the numbers, as of stage 1 (2026-09-19). Every figure here is reproduced by
the commands at the end, from stored records, without a vendor call.

## The question

Not "is the candidate better". A candidate that is a little worse on an eval but much cheaper
may still ship, and one that is statistically indistinguishable from the baseline should not be
blocked because a point estimate wobbled downward. The question is **did it get worse by more
than we tolerate**, and the tolerance is written down in the eval spec as `delta_points`, three
accuracy points by default.

## The test, per suite

Both sides score every item. Outcomes are paired by item, because items differ far more than
prompts do and an unpaired comparison throws that away. The statistic is the mean of
(candidate minus baseline) over paired items, which for binary outcomes is (better minus worse)
over n.

- **Interval.** A 95% percentile bootstrap over items, 2,000 resamples. A paired difference on
  binary outcomes is -1, 0 or +1 per item, so a resample is a multinomial count drawn as two
  binomials rather than n item draws: the same distribution, at a fraction of the time, which
  is what lets the A/A study run the gate several hundred times in a minute. A test holds the
  two forms to the same interval ends on real counts.
- **Verdict.** The suite is **non-inferior** when the whole interval sits above minus delta:
  the lower bound is greater than -3%. Equivalently, the share of resamples at or below -delta,
  `p_inferior`, is at most 0.025.
- **Second opinion.** McNemar's exact test on the discordant counts is computed and stored. It
  asks a different question (is there any change at all) and is never the verdict.

## Several suites at once

The block decision applies Holm's step-down adjustment to the `p_inferior` values of the suites
that are decided, and a suite passes when its adjusted p is at most 0.025. Each suite's own
interval is still shown uncorrected, labelled as such.

One thing to be clear about, because the plan's wording leaves it open. A non-inferiority test
rejects "the candidate is worse by delta or more". Holm across suites controls the chance of
**falsely rejecting** that, which is the chance of falsely passing a suite that really did
regress. It therefore makes the gate stricter as suites are added, not looser, and the price is
paid in false blocks. That price is what the A/A study measures, and B5 already says what to do
if it is too high: adjust delta or the repeat count, and record the reasoning. Nothing in the
code moves either of those on its own.

## The power screen

A suite with too few paired items to see a drop of delta at 80% power is not decided. It
**warns**, shows its interval, and is left out of the Holm family. The threshold is
`mselect.items_needed(delta, 0.8, ability)` from project 02, and the spec can override it per
suite with `min_items`.

Two things about that number, both from 02's own validation:

- **It is a floor.** It assumes items chosen adaptively from 02's calibrated bank, which a
  fixed suite is not, and 02 found it optimistic for large effects. Treat "118 items for three
  points" as "at least 118".
- **The bank cannot place this panel.** Its expected score tops out near 83%, and the drift
  panel scores in the nineties, so the "ability from the baseline's score" the plan describes
  cannot be read off the curve for any arm. The reference ability +0.0 is used instead, and
  the note in every power line says so. Where a baseline does land on the curve, near its flat
  top, the bank asks for absurdly few items (17 for three points at ability +4), so the answer
  at the placed ability is never allowed below the answer at the reference.

At the reference: **3,559 items for one point, 118 for three, 33 for five.** Against the
drift blocks (120, 100, 60, 40, 40, 20, 20, 20 items) that means one suite of eight is decided
at three points and five at five points. The drift suite was built to measure drift, not to
gate on, and the screen says so in print rather than blocking on twenty items.

## Local dependence, shown and not used

A hundred items of one benchmark are not a hundred independent pieces of evidence. 02 measured
the residual correlation between items on its bank, and `mselect.dependence()` turns it into a
variance inflation: on bank v1 a hundred GSM8K items are worth about ten, a hundred MMLU items
about forty-seven. For a suite whose spec names a `benchmark`, the gate computes the corrected
interval (replicates spread about the point by the square root of the inflation, point
unchanged) and prints it beside the plain one with the effective item count.

It does not decide unless the spec says `correct_for_dependence: true`, and the shipped spec
says so for no suite. 02's own v0.2.0 caveat is that the correction is a property of the bank
and the panel it was fitted on, not of the benchmark, and the same MATH items are worth about
eleven on one bank and six on another. Carrying that number to items sampled here is a claim
that has to be earned. The A/A study is where it would be earned: if the plain interval's
false-block rate is fine, the correction is not needed for the gate's purpose; if it is not,
the correction is one candidate fix among several.

## Cost and latency lines

Separate from accuracy and labelled as such. The candidate's median latency and cost per call
are compared with the baseline's, and a rise beyond the spec's `max_increase_pct` blocks on
that line alone. A line not measured on both sides warns rather than guessing.

## The A/A study: the gate against itself

Same prompt, same model, both sides. Nothing changed, so every block is a false block, and the
share of blocks is the false-block rate. The target in B5 is under 5%.

Part A's record makes the study free. Two kinds of pair are cut from the two September runs:

- **within** a run: one arm's five repeats split into two disjoint sets of two, each reduced to
  one verdict per item, one set the baseline and the other the candidate. Every ordered pair of
  disjoint sets, 30 per arm, 240 in all. Same sitting; nothing changed but which calls were
  kept. Two calls per side is fewer than a real gate run would use, so this is the harsh
  version.
- **between** two runs: the same arm on 2026-09-13 and 2026-09-16, both ways round, 16 pairs.
  Five calls per side and four days apart: the closer cousin of a real gate run.

Every pair is also scored by the rule the gate does not use, **block whenever the candidate's
point estimate is lower**, which PLAN.md B13 names as an approach expected to fail.

### What it found, 2026-09-19

| Setting | Pairs | Suites decided | False-block rate, interval rule | Block rate, point rule |
|---|---:|---:|---|---|
| delta 3, as specified, within | 240 | 1 of 8 | 7.1% (4.2 to 10.4) | 75.4% (69.6 to 80.8) |
| delta 3, as specified, between | 16 | 1 of 8 | 6.2% (0.0 to 18.8) | 81.2% (62.5 to 100.0) |
| delta 3, as specified, all | 256 | 1 of 8 | **7.0% (4.3 to 10.2)** | **75.8% (70.3 to 81.2)** |
| delta 3, every suite decided, all | 256 | 8 of 8 | 94.5% (91.8 to 97.3) | 75.8% (70.3 to 81.2) |
| delta 5, as specified, all | 256 | 5 of 8 | 60.9% (54.7 to 66.8) | 75.8% (70.3 to 81.2) |
| delta 2, as specified, all | 256 | 0 of 8 | 0.0% (0.0 to 0.0) | 75.8% (70.3 to 81.2) |

Intervals are 95% bootstrap intervals over pairs. The full table, with per-suite and per-arm
counts, is [`gate/reports/aa-2026-09.md`](../gate/reports/aa-2026-09.md).

Four things to read off it.

1. **As specified, the false-block rate is 7.0% (4.3 to 10.2).** Not shown to be under 5%; the
   point sits above it. All 18 blocks are the same suite on the same arm: `closed_form_reasoning`
   on `openweights-control`, 18 of its 32 pairs. That arm has the panel's highest same-day flip
   rate (3.6% to 4.0%) and its lowest accuracy, and on 120 items a wobble of two points cannot
   be told from a drop of three. The seven vendor arms, with flip rates from 0.2% to 1.4%,
   produced no false block in 224 pairs.
2. **The point rule blocks three quarters of the time.** B13 expected about half; it is 75.8%,
   because the drift blocks are small and two sides rarely tie. That is B13 candidate 2
   measured, and it is the argument for intervals in one number: a gate on the point estimate
   would block three of every four changes that changed nothing.
3. **The power screen is doing almost all of the work.** With every suite decided, the
   interval rule blocks 94.5% of pairs, because a single flipped item on a twenty-item suite
   is a five-point drop with an interval that reaches -15%. The screen is what turns that into
   7%, and it does so by declining to decide seven of the eight suites.
4. **The delta rows are the screen's, not the rule's.** At delta 2 nothing is decided and the
   zero is empty; at delta 5, five suites are decided and 61% of pairs block, because suites of
   40 and 60 items now reach a verdict they cannot clear. Loosening the margin without adding
   items makes the gate worse, not better, on this suite.

### What it does not claim

It does not claim the gate's false-block rate on a suite built for gating, with a few hundred
items per suite and five calls per side; that is stage 7's full-size study, on the demo
repository's own suite. It does not claim the dependence correction is right or wrong for these
items; with the plain interval already at 7%, widening it is not the direction to look first.
And it does not claim the control's blocks are a fault in the control: a model that flips 4% of
its answers between two sittings of the same question is measured correctly when a gate with a
3% margin on 120 items cannot clear it. The fix, when one is chosen, is more items or more
calls per side, and B5 says the reasoning is recorded when it is.

## Reproduce it

Needs the `gate` extra: `uv sync --all-extras`. Nothing calls a vendor.

```bash
uv run gate spec show                                   # the spec and its content hash
uv run gate run 2026-09/anthropic-alias                 # one side, every suite with its interval
uv run gate power --side 2026-09/anthropic-alias        # items needed for 1, 3 and 5 points
uv run gate compare --baseline 2026-09/anthropic-alias --candidate 2026-09-run2/anthropic-alias --no-record
uv run gate compare --baseline 2026-09/openweights-control --candidate 2026-09-run2/openweights-control --no-record
uv run gate aa --month 2026-09-run2 --baseline 2026-09 --delta 5 --delta 2
```

The second `compare` exits 1: it is the between-run false block on the control, and the reason
it prints is the one this document describes. Both decisions are the first two records in
[`gate/runs/ledger.jsonl`](../gate/runs/ledger.jsonl).

## A live, judge-graded suite (stage 4)

A pull request has no stored record, so `gate check` makes both sides live: the base branch's
prompt and model, and the pull request's, each answer the gold set's 100 questions from their
own documents, and a calibrated judge grades each answer for completeness. Two things change
from the stage-1 suites, and both make the gate stricter to set up rather than easier to pass.

### The judge's error is taken out of the difference

A judge with sensitivity *se* and specificity *sp* reports a pass with probability
(*se* + *sp* - 1) *p* + (1 - *sp*) when the true rate is *p*. On both sides of a paired comparison
that is the same line, so the difference the judge sees is the true difference times
(*se* + *sp* - 1), whatever the two rates are. Left alone, that shrinks every regression towards
zero, and the gate gets more lenient in exact proportion to how bad its judge is.

So `paired_difference` divides by that factor, and resamples *se* and *sp* from the calibration
counts in every bootstrap draw, so the interval carries the calibration's own sampling error as
well as the items'. For Gemini 3.8 Flash on completeness the factor is 0.89 (317 of 317 human
passes agreed, 145 of 163 human failures): a true ten-point drop looks like 8.9, and is decided
as ten. The power screen asks for the items needed to see the shrunk difference, not the full
one. The assumption, stated wherever the figure appears, is that the judge errs the same way on
both sides; a calibration over three answering models of different capability is the evidence
for it, and it is an assumption rather than a measurement.

A judge is licensed per task, from the stored calibration, before any call is made: same rubric
hash, same output budget, source first, kappa at or above 0.6. Neither judge passed on
faithfulness, so no live suite can be graded on it, and the pull-request comment says so.

### Why ten points, not three (B5)

This is the margin decision B5 says is taken only with the reasoning written down.

Three points is right for a 420-item programmatic suite. It is wrong for 100 items graded by a
judge, and not by a little. An unchanged prompt run twice does not give identical verdicts:
some answers change at temperature 0, and the judge itself disagrees with itself on 1.2% of
identical prompts. Each such item moves the paired difference, and the rule blocks whenever the
interval's lower end, about 1.96 standard deviations below the observed difference, falls past
the margin. Keeping false blocks under 5% needs a margin of about 3.6 standard deviations.

`uv run python -m gate.live_aa` simulates it on the real test and the real judge counts: two runs
drawn from the same per-item propensities, so every block is a false one.

| items differing between two runs | 3 pts | 5 pts | 8 pts | 10 pts |
|---|---:|---:|---:|---:|
| 3.9% | 68.5% | 39.2% | 8.2% | 2.2% |
| 6.7% | 80.2% | 60.2% | 19.2% | 9.5% |
| 11.6% | 85.8% | 72.8% | 41.0% | 26.0% |

At the gate's default three points an unchanged prompt is blocked about seven times in ten. Ten
points is the smallest round margin that keeps the false-block rate near or under 5%, **and
only if about 4% of items disagree between two runs of one prompt**. That rate is not measured
yet. The demo repository's A/A pull request measures it, and if it comes out near 7% the
false-block rate at ten points is near one in ten and the margin is revisited here, with the
measurement, before anything is tuned.

What this means in plain terms: a 100-question suite graded by a judge can guard against a
regression of ten points or more and cannot see anything smaller. The remedy is more questions,
not a narrower margin, and a narrower margin without them would be a gate that blocks at
random.

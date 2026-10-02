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

### The power function, checked against real answers (2026-10-02)

The plan asks for the power numbers to be validated here, not only taken from 02. `gate
power-check --month 2026-10` does it with the gate's own paired test on October's answers: for
each arm, the five repeats split two against two, the suites' 420 items pooled, and a hundred
random draws of each size put through the test at a three- and a five-point margin. Nothing
changed between the two halves, so the share of draws that pass is the gate's power at that
margin, and it should reach 80% where the bank says it does. The full table is
[`gate/reports/power-check-2026-10.md`](../gate/reports/power-check-2026-10.md).

| Margin | The bank asks for | Without items of discrimination 0.3 or less | Empirically, the fewest any arm needs | Empirically, the noisiest arm |
|---|---:|---:|---:|---:|
| 3 points | 118 | 222 | 120 (four arms) | 320 (`google-alias`) |
| 5 points | 33 | 57 | 80 (seven arms) | 160 (`google-alias`) |

"Empirically" is the fewest items at which the gate passed at least 80 of its 100 draws and
kept doing so at every larger size tried; the sizes tried are 40, 60, 80, 120, 160, 240, 320
and 400, so a figure is the first size that cleared, not an interpolation.

What it shows:

- **At three points the bank is right for the quietest arms and short for the rest.** The two
  Anthropic and two OpenAI configurations reach 80% at 120 items, against the bank's 118. The
  sonnet snapshot and the control pass 82% and 81% at 120 and slip to 77% at 160, which is
  within the draws' own noise (each cell's interval is about eight points either side), and so
  are counted at 240. The Google arms, whose noise floors are the highest, need 240 and 320.
- **At five points the bank is optimistic by more than half.** It asks for 33; no arm reaches
  80% below 80 items, and `google-alias` needs 160. This is 02's own caveat, that the function
  over-promises for large effects, measured here: treat its answer as a floor, as every power
  line already says.
- **It explains the A/A study's five-point row.** At five points the screen decides the suites
  with 33 items or more, including the 40- and 60-item ones, which this check says pass a
  no-change comparison well under four times in five. That is why the A/A study blocked every
  pair at five points: the suites the screen let through were too small for the margin.

### Filtering the bank on discrimination, measured and rejected (2026-10-02)

PLAN.md asks that 02's items be filtered on discrimination before their difficulties are used,
because an item that barely discriminates has a difficulty that is a division by nearly zero.
The spec now takes `power.min_discrimination`, and at 0.3 the bank keeps 16,103 of its 20,365
items. It is **not set** in the shipped spec, because of what it does to the gate:

| `drift-blocks`, 256 no-change pairs | Bank as shipped | Filtered at 0.3 |
|---|---|---|
| Items asked for, 3 points | 118 | 222 |
| Suites decided per pair, 3 points | 1 of 8 | 0 of 8 |
| False-block rate, 3 points | 7.0% (4.3 to 10.2) | 0.0% (0.0 to 1.0), and the zero is the screen's |
| Items asked for, 5 points | 33 | 57 |
| Suites decided per pair, 5 points | 5 of 8 | 3 of 8 |
| False-block rate, 5 points | 100.0% (99.0 to 100.0) | 89.5% (85.9 to 93.0) |

Filtered, the gate decides nothing on the drift blocks at three points, so its published
false-block rate would become a zero that measures the screen and not the rule. At five
points it is better than the bank as shipped and still blocks nearly nine no-change pairs in
ten, because the check above says five points needs about 80 items and the filter lets a
60-item suite through. Neither setting of the bank is the right screen for this panel; the
empirical numbers above are closer to it than either. Choosing between them changes the
margin's evidence, which this document says is changed only with a measured reason. **Decided
2026-10-02: the bank stays as shipped.** The filter would make the gate decide nothing at three
points, and the unfiltered 118 is what the check above measures the quietest arms needing, so
it moves the screen away from the measurement rather than towards it (PLAN.md B13 item 4,
`docs/rejected.md`). The figures are reproducible with the spec copied and
`min_discrimination: 0.3` added under `power`, and `gate aa --month 2026-09-run2 --baseline
2026-09 --delta 5 --no-decide-all --spec <that copy>`.

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
| delta 3, every suite decided, all | 256 | 8 of 8 | 100.0% (99.0 to 100.0) | 75.8% (70.3 to 81.2) |
| delta 5, as specified, all | 256 | 5 of 8 | 100.0% (99.0 to 100.0) | 75.8% (70.3 to 81.2) |
| delta 2, as specified, all | 256 | 0 of 8 | 0.0% (0.0 to 1.0) | 75.8% (70.3 to 81.2) |

Intervals are 95% bootstrap intervals over pairs, Jeffreys where every pair agrees (a bootstrap
of 256 zeros printed "0.0 to 0.0" here until 2026-09-27). The two rows with 100.0% were 94.5% and
60.9% before the rule of three below, which is why they moved; the headline row did not. The full table, with per-suite and per-arm
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
uv run gate power-check --month 2026-10                 # the power function against real answers
```

The second `compare` exits 1: it is the between-run false block on the control, and the reason
it prints is the one this document describes. Both decisions are the first two records in
[`gate/runs/ledger.jsonl`](../gate/runs/ledger.jsonl).

## Unanimous counts: the rule of three (2026-09-27)

The paired test resamples the counts of items that got worse and better at their observed rates.
When a count is zero, a bootstrap can only ever redraw zero: a candidate with no item worse than
the baseline was passed with an interval of exactly (+0.0 to +0.0) and a p-value of 0, a
certainty that nothing could have got worse. The first gated pull requests printed exactly that,
and "100.0% (100.0 to 100.0)" beside it for each side. But no disagreement in n items bounds the
rate of getting worse near 3/n, not at 0 (the rule of three): two sides that agree on all 60
items leave an interval of about -5 to +5 points, not (0, 0).

So `gate.stats.rate_draw` draws a count of 0 or n from its Jeffreys posterior, Beta(k + 1/2,
n - k + 1/2), in every resample, for the worse and better counts and for the judge's sensitivity
and specificity, and `bootstrap_share` gives Jeffreys at 0 or n. Every other count keeps the
percentile bootstrap with no extra random number drawn, so any comparison with discordance on
both sides and an imperfect judge gets the interval it got before, bit for bit. Decisions made
under the change carry gate version `0.1.0.dev2`; the ledger's earlier records keep theirs.

What it changed, measured on the A/A study above:

- **The headline does not move**: 7.0% (4.3 to 10.2) false blocks as specified, 75.8% under the
  point rule. The one suite decided at three points has 120 items, where a zero count bounds the
  drop at about 2.5 points, inside the margin.
- **Small suites can no longer pass on having seen nothing.** With the power screen off, or at
  five points, the suites of 20 to 40 items now block every A/A pair (the two rows marked above).
  That is correct, and it is a finding about the power screen: `mselect` says 33 items detect a
  five-point drop, yet 33 items with no disagreement at all cannot rule one out (0 of 33 bounds the
  rate of getting worse near 7%). The power numbers were already documented as a floor; this is the floor measured. The
  screen keeps those suites out of the decision as specified, so no shipped verdict changes.
- **The live suite still passes an unchanged prompt**: with 0 of 100 disagreements the interval's
  lower end is about -3.0 points, about -3.4 once the judge's error is divided out, against a
  ten-point margin.

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
well as the items'. For Gemini 3.8 Flash on completeness the factor is 0.90 under rubric v3
(317 of 317 human passes agreed, 147 of 163 human failures; 0.89 and 145 under v2): a true
ten-point drop looks like 9.0, and is decided as ten. The power screen asks for the items needed to see the shrunk difference, not the full
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
| 3.9% | 71.8% | 39.2% | 6.5% | 2.0% |
| 6.7% | 79.2% | 61.0% | 18.8% | 8.8% |
| 11.6% | 86.0% | 72.5% | 40.2% | 24.0% |

Under rubric v3's judge counts (2026-09-29). Under v2's the ten-point column read 2.2%, 9.5% and
26.5%. The judge is slightly better, so no conclusion below changes.

At the gate's default three points an unchanged prompt is blocked about seven times in ten. Ten
points is the smallest round margin that keeps the false-block rate near or under 5%, **and
only if about 4% of items disagree between two runs of one prompt**. That rate was not measured
when the margin was set; it is now, below, at 0.0% (0.0 to 0.3) for a prompt at the ceiling. The demo repository's A/A pull request measures it, and if it comes out near 7% the
false-block rate at ten points is near one in ten and the margin is revisited here, with the
measurement, before anything is tuned.

**First evidence, 2026-09-27.** The table was recomputed under the rule of three below and moved
by at most 2.3 points in any cell, 0.5 at ten points. The demo's first pull requests are not an
A/A pair, but the nearest of them, a rewording of the same three instructions
([#1](https://github.com/Peter-A-P/regulated-qa-demo/pull/1)), had **0 of 100 items** judged
differently from the base prompt, and so did the next
([#2](https://github.com/Peter-A-P/regulated-qa-demo/pull/2)). That is under the table's lowest
row, so ten points keeps false blocks near 2% or lower, with the caveat that both sides sat at a
completeness of 100%, where there is little room to disagree ([`gate-action.md`](gate-action.md)).

**Measured, from 2026-10-02.** `gate live-aa run` answers and judges the demo repository's base
prompt live, again and again with no cache, and `gate live-aa report` puts every ordered pair of
runs through the gate ([`gate/reports/live-aa.md`](../gate/reports/live-aa.md)). It runs in the
`live-aa` workflow, since it spends, and its intervals resample runs, not pairs, because each
run is in many pairs. The share of items that differ between two runs is the number the table
above needed.

**Result, 2026-10-02: 20 runs, US$3.66.** Claude Haiku 4.5 on the demo's base prompt
(`ade40cb668ff1e93`), each run 100 answers and 100 judgements with no cache. Every one of the
2,000 answers was judged complete, so:

| | Measured | Assumed for the margin |
|---|---|---|
| Items whose verdict differed between two runs | 0.0% (0.0 to 0.3) | about 4% |
| False-block rate at ten points, 380 ordered pairs | 0.0% (0.0 to 11.7), 0 blocked | about 2% |

The measurement does not contradict the margin: discordance is under the table's lowest row,
where ten points false-blocks about 2% of the time, and none of the 380 pairs was blocked. **The
margin stays at ten points**, and the measurement is not a reason to narrow it, for two reasons.
The base prompt sits at the ceiling, 100 of 100 on every run, and an item that is never failed
cannot disagree with itself; a prompt scoring in the eighties, with items near the line, would
disagree more, and the table's rows are what that looks like. And the false-block interval is
wide because twenty runs are about twenty independent pieces of evidence, not 380: its upper end,
11.7%, does not rule out the margin being too narrow, let alone too wide. What it does establish is
that this judge, on this suite, does not invent disagreement: twenty sittings of the same prompt
were graded identically, item for item.

What this means in plain terms: a 100-question suite graded by a judge can guard against a
regression of ten points or more and cannot see anything smaller. The remedy is more questions,
not a narrower margin, and a narrower margin without them would be a gate that blocks at
random.

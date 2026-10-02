# The gate on pull requests

`action/` is a composite GitHub Action that runs the release gate on a pull request that
changes a prompt or a model. It is the third surface on the one library (PLAN.md B2.1): what it
decides can be reproduced with `gate check` from a checkout.

## What it does

1. Checks out the base branch beside the pull request.
2. Runs `gate check`: both sides answer every question of each suite in `gate.yaml`, a
   calibrated judge grades the answers, and the paired, one-sided non-inferiority test decides,
   with the judge's error taken out of the difference (`docs/gate-statistics.md`).
3. Posts one comment on the pull request, and edits that same comment on every later push.
4. Exits non-zero on a block, so branch protection can require the check.
5. Keeps every answer, as the run's `gate-answers-<run id>` artifact for 30 days (since
   2026-09-28). `answers.jsonl` pairs both sides' answer to each question with the judge's reply,
   including replies served from the cache. The call ledger and boundary's raw store, keys
   redacted, sit beside it. Faithfulness is not gated, so a person reading these is the only
   check on it. Before this, the answers stayed on the runner, and so did the only way to see
   why a verdict came out as it did.

## The rules that make it hard to fool

- **The base branch sets the rules.** The margin, thresholds and suites come from the base
  branch's `gate.yaml`. The pull request supplies only the prompt and the model. A pull request
  that edits `gate.yaml`'s rules is told so in its comment, and the edit applies once merged.
- **A judge grades only what it was cleared for.** `gate check` calibrates the named judge from
  the stored record and refuses, before a call is made, a judge whose kappa on the task is below
  0.6, whose calibration was made under a different rubric, or whose output budget differs from
  the one it was calibrated at. Today that means completeness only.
- **`pull_request`, never `pull_request_target`.** The gate sends the pull request's prompt to
  vendors with the repository's keys; `pull_request_target` would give those keys to a fork.
- **Pin the gate.** `gate-ref` should be a commit. A moving ref moves the gate under a pull
  request that has not changed.

## Using it

A repository needs a `gate.yaml` and a prompt file; `examples/regulated-qa-demo/` is a complete
one. The workflow:

```yaml
on:
  pull_request:
    paths: [prompts/**, gate.yaml]
permissions:
  contents: read
  pull-requests: write
jobs:
  gate:
    runs-on: ubuntu-24.04
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: Peter-A-P/ai-release-gate/action@<commit>
        with: { gate-ref: <commit> }
```

### Where the decision goes

The comment is the verdict a reviewer reads; it is edited in place, so it holds only the latest
one. Every decision is also written as a ledger record, `decision.jsonl` in the run's
`gate-answers-<run id>` artifact, kept 90 days. The record holds:

- both sides (model, settings and prompt hash), the spec, the graders and each judge's licence;
- each suite's paired difference with its interval, and its verdict and reasons;
- the occasion: repository, pull request, commit, run, and each side's accuracy with its
  interval, calls, cost and latency.

The occasion sits outside the record's id, so a re-run that decides the same thing is the same
decision on another occasion. The `ledger` workflow here reads those artifacts nightly and
appends each new record to `gate/runs/ledger.jsonl` with `gate ledger import`. That command
refuses a record whose id does not match its content. The workflow then rebuilds, from the
ledger alone:

- `gate/reports/decisions.md`, every decision newest first;
- `gate/reports/model-cards/`, one card per model and prompt the gate has measured.

Runs before 2026-09-30 wrote no record. Their decisions (#1 to #8 on the demo) are in the pull
requests' comments only, and they are not reconstructed.

## Cost

Each side is 100 answers and 100 judgements. At the prices measured on the gold set, about
US$0.0009 an answer from Haiku 4.5 and US$0.0011 a judgement from Gemini 3.8 Flash, that is
about US$0.20 a side. The base branch's side is cached after its first run, because a reply is
reused for a byte-identical request, so a typical pull request after the first costs about
US$0.20. The comment states what each run spent and how many calls the cache saved.

## What it does not do

- It does not grade faithfulness. No judge passed calibration on it (kappa 0.04 and 0.11 under
  rubric v3; 0.07 and 0.11 under v2).
- It cannot see a regression smaller than about ten points on a 100-question suite; see "Why
  ten points" in `docs/gate-statistics.md`.
- The development cache is for pull requests only. Part A's monthly drift run never uses one.

## The first three pull requests, 2026-09-27

On [regulated-qa-demo](https://github.com/Peter-A-P/regulated-qa-demo), each answered live on the
100 gold questions by Haiku 4.5 and graded for completeness by Gemini 3.8 Flash (kappa 0.914):

| Pull request | Expected | Verdict | Baseline | Candidate | Difference | Cost |
|---|---|---|---|---|---|---|
| [#1](https://github.com/Peter-A-P/regulated-qa-demo/pull/1) reword, same meaning | pass | pass | 100.0% | 100.0% | +0.0 | US$0.34 |
| [#2](https://github.com/Peter-A-P/regulated-qa-demo/pull/2) state the document's figures | pass | pass | 100.0% | 100.0% | +0.0 | US$0.36 |
| [#3](https://github.com/Peter-A-P/regulated-qa-demo/pull/3) one sentence of 15 words at most | **block** | **pass** | 100.0% | 99.0% | -1.1 (-3.5 to +0.0) | US$0.33 |

#1 and #2 were merged; #2 was gated again first on the combined prompt, and passed at 0 of 100
items judged differently. #3 stays open as the record of the pass that should have been a block.

The machinery worked end to end: the base branch's rules, both sides answered live, a licensed
judge, its error divided out of the difference, one comment per pull request, costs as
estimated. **The verdict on #3 is a finding, not a malfunction.** The judge scored answers cut to
one sentence 99% complete, and the unchanged prompt 100%: on these questions, with this rubric,
"complete" is at its ceiling for any answer that states the main point, so the suite has no room
to show the regression #3 was written to be. A ten-point margin on a suite at 100% blocks
nothing short of a collapse. That is the same lesson as the margin itself (`docs/gate-statistics.md`),
from the other side: the suite needs items a short answer fails, or a grader that asks for more
than the main point, before it can gate brevity. Neither is changed here; the rubric is the
standard (`docs/judge-rubric.md`) and is not revised to make a demo come out as expected.

Two more things the comments show:

- **Zero-width intervals in the gate's own statistics**: "100.0% (100.0 to 100.0)" and
  "+0.0% (+0.0 to +0.0)" when every item agrees. Fixed the same day in f274a45, with the reasoning
  in `docs/gate-statistics.md` ("Unanimous counts"), and the demo moved to it
  ([#4](https://github.com/Peter-A-P/regulated-qa-demo/pull/4)). #3, re-run under it against the
  merged #1 and #2, now reads 100.0% (97.5 to 100.0) against 99.0% (97.0 to 100.0), a difference
  of -1.1 (-3.5 to +3.4): still a pass, and now an honest one.
- **The development cache saved little** (34, 18 and 0 of about 400 requests), because Actions
  caches written on one pull request's branch are not visible to another's. The base side is
  paid for on every pull request until a cache is written from `main`.

## #6: a regression the model declined to make, 2026-09-28

[#6](https://github.com/Peter-A-P/regulated-qa-demo/pull/6) was written to be blocked. It is the
kind of change a compliance review asks for. The prompt tells the model not to give amounts, time
limits or conditions, and to send the customer to the document or the regulator instead. It
passed: 100.0% (97.5 to 100.0) against 100.0% (97.5 to 100.0), a difference of +0.0 (-3.4 to
+3.4), for US$0.39.

To see why, the gate now keeps every answer (point 5 above), and #6 was re-run on the new gate
from its cache for US$0.00. **The regression never happened.** Haiku 4.5 ignored the
instruction:
- 47 of the 100 candidate answers still contain a figure, exactly as many as the base branch's.
- The candidate states the facts and then adds a referral, "you should contact your financial
  institution directly", on 52 answers. Its answers got longer, not shorter: a median of 75 words
  against 47.5.

The judge's 100% is right. Answers containing every expected phrase fell from 75 to 62 of 88. All
16 items that lost a phrase were read, and every one keeps the substance in other words: "do not
lend money directly to you", "last in line", "Loss of your job". That is also a small argument
for the rubric's rule that `must_mention` is a checklist, not a scoring rule: a literal phrase
match would have called 16 complete answers incomplete.

So #6 shows the gate passing a change that did not regress. It does not show it blocking one.
The prompt was not made stronger and re-run until it blocked. That would be tuning the demo
until it came out as expected, the same error as tuning a rubric. #6 stays open, not to be
merged, as the record. A block that means something comes from the suite that brevity can fail
(`gate/gold_multipart.py`, a draft under review), with #3 re-run on it. Until then the block path
is exercised only by the tests, end to end on a fake vendor (`tests/test_gate_live.py`).

## The multi-part stratum: the suite can see brevity, the judge cannot (2026-09-29)

#3 passed because the 100 questions left no room: a one-sentence answer states the one fact most
of them ask for. So 50 questions were written that each ask for two or three things
(`gate/gold_multipart.py`), and Peter reviewed them. Three models answered each one, 150 answers:
two under the gold set's ordinary prompt, and one under #3's one-sentence limit. Peter labelled
all 150 blind, and both judges read them.

**By Peter's reading, the suite does what it was built for:**

| Multi-part answers | Complete, by hand |
|---|---|
| 100 under the ordinary prompt | 99 (99%) |
| 50 under the one-sentence limit | 25 (50%) |

That is a drop of about 49 points, from exactly the change #3 made. A ten-point margin would
block it with room to spare, if the suite could be graded.

**It cannot, with either judge.** The gate's judge, Gemini 3.8 Flash, has a kappa of 0.914 on the
first hundred's completeness. Here it is 0.313 (0.106 to 0.511): refused, below the 0.6 floor.
It found 6 of the 25 short answers Peter marked incomplete, a specificity of 23.1% (7.7 to
38.5), and called nearly everything else complete. GPT-5.4 mini is worse, at 0.121. Both are in
`docs/judge-calibration-*-multipart.md`, beside the first hundred's reports, which are unchanged.
The judge's reading on this stratum is no licence to grade it, so `gate check` refuses a suite
on it. That refusal is the rule working, not a fault.

A literal check, "complete when every expected phrase is in the answer", fails the other way
round. It catches all 26 incomplete answers but calls 100 of the 124 complete ones incomplete,
because a paraphrase is not the phrase (kappa 0.077). That is the second time the rubric's
"`must_mention` is a checklist, not a scoring rule" has been the right call (#6 was the first).

What this says about the gate: **a judge calibrated on one kind of question is not calibrated on
another.** 0.914 on questions that ask for one fact said nothing about questions that ask for
three. Had the licence been carried across, the gate would have run the new suite, taken the
judge's near-100% for both sides, and passed #3 again. It would then have looked like a measured
result, one built on an instrument that sees a quarter of the failures. Licensing per stratum is
what stopped that.

Not done, deliberately:
- **The rubric was not changed.** The judge disagreeing with Peter is the finding, not a prompt
  to reword the standard until it agrees.
- **No false-block study or re-run of #3 on the new suite.** Both need a licensed judge, and
  there is none.

The next honest step is a stronger judge, calibrated against the same 150 labels, and licensed
for this stratum only if it clears the floor.

### Rubric v3: the judge was never told two of the rubric's rules (found 2026-09-29)

Reading the judge's prompt beside `docs/judge-rubric.md` after the refusal above showed the real
cause. The rubric gives five reasons to say an answer is not complete. The prompt carried three,
and was missing:
- "The answer is so vague that a reader still does not know the answer."
- "The answer covers only part of what was asked, and the missing part is the substance rather
  than a detail."

The second is the rule Peter labelled the short answers by, and the judge was never given it.
All it was told was that a brief answer can be complete. So the two were applying different
standards, and kappa 0.313 measured the gap between the standards, not the judge. This is the
same failure as rubric v2 on 2026-09-22, in another clause. The spot-check test passed both
times because it never looked at these lines. Two judges allowed to think changed nothing
(0.313 and 0.324), which fits: thinking harder about the wrong standard is still the wrong
standard.

**The fix, fixed in advance.**
- Rubric v3 ports the two missing reasons into the prompt, word for word. It adds nothing else
  and reinterprets nothing. The human rubric is unchanged, so no label is re-read.
- A new test maps each of the rubric's five reasons to its line in the prompt, and fails when a
  reason is added without one.
- This was committed and pushed before any judge read anything under v3.
- The v2 readings and their four reports stay in the record, as `*-rubric-v2.md`.

**Published whatever it shows.** Under v3 every judge is recalibrated from scratch, on the first
hundred and on the multi-part fifty, against the same labels.
- If the demo's judge falls below 0.6 on the first hundred, the demo's gate loses its licence,
  and that is reported as the result.
- If a judge clears 0.6 on the multi-part stratum, the false-block study and #3's re-run go
  ahead on it.
- If none does, the finding stands as written above.

**The result under rubric v3, 2026-09-29.** Every judge was recalibrated on the same labels, as
committed above, for US$3.96. Completeness kappa:

| Judge | First hundred, v2 | First hundred, v3 | Multi-part, v2 | Multi-part, v3 |
|---|---|---|---|---|
| Gemini 3.8 Flash (the gate's) | 0.914 | **0.924** (0.886 to 0.958), licensed | 0.313 | **0.447** (0.218 to 0.642), refused |
| GPT-5.4 mini | 0.790 | 0.743 (0.675 to 0.804), licensed | 0.121 | 0.214 (0.025 to 0.416), refused |
| Gemini 3.8 Flash, thinking high | | | 0.313 | 0.404 (0.180 to 0.608), refused |
| GPT-5.4 mini, reasoning high | | | 0.324 | 0.391 (0.161 to 0.580), refused |

- **The fix was real.** Every judge moved towards Peter's reading on the multi-part answers.
  The gate's judge now catches 9 of the 25 incomplete short answers, up from 6.
- **It was not enough.** No judge clears 0.6 on the multi-part stratum, so, as committed, the
  finding stands:
  - the suite can see a brevity regression that no judge can grade;
  - the false-block study and #3's re-run on it still wait for a licensed judge.
- **The demo keeps its judge**, at 0.924 on the first hundred, so the v3 wording cost the
  existing gate nothing.
- **Faithfulness** is still refused everywhere: 0.114 and 0.040 on the first hundred.

The four v3 reports on the first hundred and the multi-part fifty are
`docs/judge-calibration-*.md`, and v2's are `*-rubric-v2.md`. Both sets rebuild byte for byte
from the record.

What is left to try is a stronger model, one that needs a new dated price file. That file would
then also be the monthly drift run's price list, so it waits until after the October 1 run.

### A larger judge, committed before it is run (2026-09-30)

Two judges were added to `gate/specs/gold-judges.yaml` before any call was made to either:

| Judge | Identifier | Settings |
|---|---|---|
| `openai-judge-large` | `gpt-5.4-2026-03-05` | reasoning none, temperature 0, as GPT-5.4 mini |
| `google-judge-large` | `gemini-3.1-pro-preview` | thinking low, as Gemini 3.8 Flash |

- **The hypothesis** is the next cheapest one after thinking: a larger model. Size is the only
  change, and each judge keeps its smaller sibling's settings.
- **The bar is unchanged.** Each is calibrated from scratch on the same 150 multi-part labels,
  under rubric v3, and needs kappa 0.6 on the stratum or it is refused. Both results are
  published, whatever they are, as every judge's has been.
- **A caveat on the Google judge.** Google offers no stable Pro model and no dated one, so it is
  a preview identifier and can change under its name. If it is licensed, that licence is weaker
  than the others and is quoted with that caveat.
- **If one is licensed**, it grades the false-block study on the multi-part suite and the re-run
  of #3 there. **If neither is**, the finding above stands as the project's result on multi-part
  completeness, and what comes next is decided and written here then.
- **Prices.** They are in `drift/config/prices/2026-10-01.yaml`, which carries every earlier rate
  unchanged, and a test holds it to that. It was merged on 2026-10-01 only once the October
  drift run had started on the commit before it. Each of that run's jobs reads the commit it
  started on, so the run was priced by 2026-09-12.yaml.

**Results, 2026-10-01.** Both were run on the same 150 multi-part answers, under rubric v3, for
US$1.16 together. Both identifiers were first re-confirmed live (run 36865991918). They were
judged at their siblings' budgets: 64 tokens for GPT-5.4 and 1024 for Gemini Pro. No verdict
was unparseable. Completeness:

| Judge | Kappa | Incomplete answers caught, of the 26 Peter marked |
|---|---|---|
| GPT-5.4 (`openai-judge-large`) | 0.508 (0.282 to 0.696), refused | 10 |
| Gemini 3.1 Pro (`google-judge-large`) | 0.313 (0.106 to 0.511), refused | 6 |
| Gemini 3.8 Flash, for comparison | 0.447 (0.218 to 0.642), refused | 9 |

- **Neither passes.** GPT-5.4 is the closest of the six judges tried, and still misses 16 of
  the 26. Gemini Pro does worse than the Flash model the gate already uses.
- **Size was not the fix.** Every judge tried, from the smallest to these two, calls most of
  the incomplete short answers complete. The finding stands as committed: the suite can see a
  brevity regression, and no judge tried can grade it.
- **Faithfulness** stays refused: 0.206 and 0.235.

The reports are `docs/judge-calibration-openai-judge-large-multipart.md` and
`docs/judge-calibration-google-judge-large-multipart.md`, and both rebuild byte for byte from
the record.

## #11: the first block, 2026-10-02

[#11](https://github.com/Peter-A-P/regulated-qa-demo/pull/11) is the block path run live for the
first time. The prompt is the kind that ships during an incident: while answers are being
reviewed, reply to every message with one hand-off sentence and answer nothing. Unlike #6, it
asks for something the model has no reason to refuse, so the regression actually happens. It
is not #6 made stronger until it blocked. #6 stays open as the record of a change the model
declined to make, and #11 is a separate change, written to exercise the one path no pull request
had reached.

**Blocked.** The baseline was 100.0% (97.5 to 100.0) complete and the candidate 0.0% (0.0 to 2.5):
100 items worse, none better. The latency and cost lines passed, since a one-sentence reply is
faster and cheaper, and the accuracy line blocked on its own. 400 vendor calls, US$0.37.

What it shows: the live path decides a block as it decides a pass. The base branch's rules
govern, both sides are answered and judged live, and the licensed judge's error is divided out
of the difference. What it does not show: anything about a regression smaller than a collapse.
A ten-point margin on 100 questions can see nothing finer (`docs/gate-statistics.md`), and #3
remains the record of a real regression this suite cannot see.

**Two defects it found, both fixed the same day:**
- **The corrected difference read -110.9% (-116.9 to -104.5).** Dividing a -100% raw difference by
  the judge's Youden index, 0.90, carries it past what a difference can be. The correction is now
  clamped to -100% to +100%, in the point and in every resample (`gate.stats.paired_difference`).
  No earlier decision was near either end, so none moves.
- **The candidate's corrected rate read 0.0% (0.0% to 0.0%)**, a bare number wearing brackets.
  The judge said yes less often than its own false-positive rate, so Rogan-Gladen fell below zero
  in nearly every resample and the clamp at 0 made the interval look certain. The comment now
  says when the clamp decided an interval.

The comment on #11 was written by the gate as pinned then (`783ccd4`), so it shows both defects.
It is kept as written, like every record. The demo picks up the fixes when it is next re-pinned.

## Every check's spend on the record (2026-10-02)

04's invoice check of September found Anthropic billing US$1.07 of gate checks on 2026-09-27 and
09-28 that no ledger held. The cause was not lost rows but lost files: the six paid runs on those
days came before the action kept anything (the artifact step arrived in `ac89380`, on 09-28 at
20:46), so each run's call ledger went with its runner. The one artifact from then, run
36467851453, holds an empty ledger correctly: it was #6 re-run from the cache, which paid for
nothing. #11's artifact holds 400 rows for its 400 paid calls. Those September rows cannot be
recovered.

So that a gap is seen the day it happens:
- `gate check` checkpoints its call ledger into one file and writes `ledger-check.json` beside the
  answers: the rows the ledger holds against the calls the run paid for. A step in the action
  fails, visibly and without changing the verdict, when they disagree.
- The nightly `ledger` workflow keeps each gate run's call ledger, when it has rows, under
  `gate/runs/pr-ledgers/`, and `push-ledgers` sends it to the portfolio's central ledger like any
  other committed ledger.

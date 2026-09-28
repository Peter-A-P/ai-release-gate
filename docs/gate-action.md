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

## Cost

Each side is 100 answers and 100 judgements. At the prices measured on the gold set, about
US$0.0009 an answer from Haiku 4.5 and US$0.0011 a judgement from Gemini 3.8 Flash, that is
about US$0.20 a side. The base branch's side is cached after its first run, because a reply is
reused for a byte-identical request, so a typical pull request after the first costs about
US$0.20. The comment states what each run spent and how many calls the cache saved.

## What it does not do

- It does not grade faithfulness. No judge passed calibration on it (kappa 0.07 and 0.11).
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
  "+0.0% (+0.0 to +0.0)" when every item agrees. Fixed the same day in 75737ef, with the reasoning
  in `docs/gate-statistics.md` ("Unanimous counts"), and the demo moved to it
  ([#4](https://github.com/Peter-A-P/regulated-qa-demo/pull/4)). #3, re-run under it against the
  merged #1 and #2, now reads 100.0% (97.5 to 100.0) against 99.0% (97.0 to 100.0), a difference
  of -1.1 (-3.5 to +3.4): still a pass, and now an honest one.
- **The development cache saved little** (34, 18 and 0 of about 400 requests), because Actions
  caches written on one pull request's branch are not visible to another's. The base side is
  paid for on every pull request until a cache is written from `main`.

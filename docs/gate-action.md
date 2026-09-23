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

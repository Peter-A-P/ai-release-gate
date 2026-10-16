# Architecture

Four figures, one per mechanism: the two halves of the project and the dashboard they share,
one monthly drift run, one pull request through the gate, and how each published number is
produced. Each names the module that implements what it shows; [PLAN.md](../PLAN.md) says why,
and [your-llm-eval-has-no-error-bars.md](your-llm-eval-has-no-error-bars.md) makes the argument
for a reader who has never run an eval.

## The system

![A frozen suite is run monthly against eight model configurations through the gateway and graded by a program into an append-only record; a judge licensed against hand labels and a paired non-inferiority test decide pull requests on a real repository; both halves and the red-team rates are exported nightly to a static dashboard.](architecture/system.svg)

Part A, on the left, is the drift record. The frozen suite (`drift/suite`, 420 questions
content-hashed, 20 of them held out and never published) is run on the first of every month by
a GitHub Actions workflow with one job per provider (`.github/workflows/drift.yml`) through the
portfolio gateway in pass-through mode, so nothing is retried, cached or rewritten and every
call is costed. A program grades every answer (`drift.graders`), with one grading function for
live runs and regrades and its hash stamped on each record, into an append-only record of raw
responses (`drift/runs`) from which the report (`drift.analysis`) can be regenerated offline for
nothing. Part B, on the right, is the gate: a gold set of 480 answers labelled by hand
(`gate/gold`) licenses a judge by kappa and checks the labeller against their own second
reading (`gate.judge`); the gate runs as a GitHub Action on pull requests in
`regulated-qa-demo`, answering both sides live and judging them (`action/`, `gate.live`,
`gate.decision`); every decision goes to the ledger and the model cards (`gate.ledger`,
`gate/reports`); the red-team suites (`gate.redteam`) run 700 frozen items on four models. In
the middle sit what both halves share: `mselect` from project 02 for the power function, and
`gate export`, which writes every page and
JSON document byte for byte each night (`.github/workflows/dashboard.yml`) to
gate.peterparker.ca on Azure Static Web Apps and reads the build id back to confirm the
deployment.

## One monthly drift run

![On the first of the month a planning job sizes the run from the panel and the price list, one job per provider asks every frozen question five times of each of that provider's arms through the gateway in pass-through mode, a program grades every answer, and a collecting job folds the arms into the month's record, writes the report and commits it.](architecture/drift-run.svg)

The schedule fires at 06:00 UTC on the first (GitHub starts it hours late). The `plan` job reads
`panel.yaml` and the dated price list and sizes the abort cap from the expected cost. The `run`
job fans out one job per provider, Anthropic with three arms, OpenAI and Google with two each
and the open-weights control on Together, and within a job asks the arms one after another
with a pause sized to the vendor's rate limit, every call through the gateway in pass-through
mode. Each arm answers all 420 questions five times; the held-out items' outputs are replaced
by their hash before anything is committed (`drift.runner.records`). The program graders
(`drift.graders`) mark every answer, and the refusal block, 20 questions asked five times, is
read by hand, blind to the model. The `collect` job folds the arm directories into the month,
compares it with the previous run, writes the report (`drift/reports/<month>.md`) with the
same-day noise floor, the change against last month, the refusals and the cost per thousand
calls, writes the README table itself between its markers, and commits; the dashboard is
rebuilt at 07:40 and the call costs are pushed to the central ledger
(`.github/workflows/push-ledgers.yml`).

## One pull request through the gate

![The gate answers both sides of a pull request live, has a licensed judge grade every answer, corrects the judge's own error out of the difference, runs a paired non-inferiority test at a stated margin with a power screen, and posts a verdict whose evidence goes to the ledger and the model cards.](architecture/gate-decision.svg)

A pull request on `regulated-qa-demo` changes a prompt or a model. The Action
(`action/action.yml`, `gate.live`) answers both sides live with no cache, through the gateway
with a spend cap per check, on the suite the gate guards (`gate/specs`). The judge, Gemini 3.8
Flash, licensed at kappa 0.924 against the 480 hand labels in `gate/gold` and holding its
licence against the labeller's blind second reading at kappa 0.851, grades every answer, and
its own error rate is taken out of the difference (`gate.judge`). The paired non-inferiority
test (`gate.stats`, `gate.power_check`) compares the sides item by item at a ten-point margin
with a bootstrap interval, after a power screen built on project 02's `items_needed`; the A/A
study (`gate.live_aa`, `gate.aa`) is the gate run against itself where nothing changed, which
is where its false-alarm rate comes from. The verdict, pass or blocked with the evidence, is
posted back on the pull request, and each side's interval, cost and latency go to the ledger,
`decisions.md` and the model cards (`gate.ledger`, `gate.cards`). Another project can hand the
gate its own graded outcomes through the adapter and get the same decision and record
([gate-adapter.md](gate-adapter.md)).

## How the published numbers are produced

![Each number in the README comes from a committed input through one command into a stored report, and every table is written between markers so a reader can regenerate it offline from the record.](architecture/measurement.svg)

The drift table comes from the three official runs in `drift/runs`, regraded by
`drift.analysis.report` into the noise floor per arm and the change against the previous run.
The gate's false-alarm rate comes from the A/A study: the two September runs cut into 256
pairs where nothing changed, then 380 pairs on the live suite (`gate/reports/live-aa.md`). The
judge licences come from calibrating six judges under three rubrics against the 480 hand
labels, a hundred of them reread blind two weeks later (`docs/judge-calibration-*.md`,
`docs/judge-intra-rater.md`). The red-team rates come from 700 frozen items on four models,
graded by programs with the refusal column read by hand (`gate/redteam/runs`). The decisions
table comes from the gate's own ledger over the pull requests it has checked. Every number
carries a 95% interval, every table is written between markers in the README by its command,
and the dashboard is exported from the same committed files by the same code.

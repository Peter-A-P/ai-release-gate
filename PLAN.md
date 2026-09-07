# Plan: AI Release Gate

**Written:** 2026-09-06. **Status:** plan only, nothing built.

Two phases, one repository:

| Phase | What | When | Section |
|---|---|---|---|
| **A. Drift record** | A frozen suite run monthly against the major vendors, from September 2026, so a twelve-month record exists by the time anyone asks | Setup Sep 2026; runs monthly through Sep 2027 | Part A |
| **B. Release gate** | Calibrated judges, confidence intervals, power analysis, a GitHub Action that blocks a regression, red-team suites, an audit trail, and a dashboard carrying the drift record | 8 weeks, Dec 1 2026 to Jan 31 2027 | Part B |

Phase A starts now because a longitudinal record cannot be created retroactively. Phase B
is the flagship build and reuses phase A's runner, storage and graders. Project 02 (Model
Selection at a Tenth of the Cost) delivers the item bank and power function that phase B's
statistics depend on, by Nov 29 2026.

---

# Part A. Monthly frontier-model drift runs

## 1. What this produces

A public, month-by-month record of how the major vendors' "frozen" language models change,
measured on a fixed suite that never changes, with enough statistical care that a
three-point move can be called signal or noise.

The number a stranger can check, per model per month:

| Metric | Definition |
|---|---|
| Accuracy | Share of gradeable items answered correctly, with a 95% bootstrap CI |
| Item flip rate (month over month) | Share of items whose graded outcome changed since the previous run, paired by item |
| Same-day flip rate (noise floor) | Share of items whose outcome differs across k repeats within one run |
| Output stability | Share of items whose normalised output text is identical across k repeats |
| Refusal rate | Share of items refused, split by "should answer" and "should refuse" probes |
| Latency p50 / p95 | Wall-clock per call, from the runner |
| Cost per 1,000 items | From returned token counts and the published price on run day |

**Drift is declared** for a model in a month when the month-over-month flip rate exceeds
the upper 95% bound of that model's same-day flip rate. That definition is the heart of the
design: without a same-day noise floor, every change looks like drift and none can be
defended.

## 2. Design decisions

### 2.1 Programmatic grading only, no LLM judge

Every item in the drift suite has a deterministic grader: exact match after normalisation,
numeric tolerance, regex, JSON schema validation, or a constraint checker. No model grades
another model here. An LLM-as-judge would drift too, and its drift would be
indistinguishable from the drift being measured. Judge calibration belongs to phase 2,
where humans label a gold set.

Consequence: the suite measures capability, instruction following, formatting and refusal
behaviour, not open-ended quality. That is stated in the README as the honest limitation.

### 2.2 Two arms per vendor, plus a control

| Arm | What is called | What it measures |
|---|---|---|
| Snapshot | A dated, pinned model identifier | Whether "frozen" actually means frozen |
| Alias | The vendor's floating "latest" identifier for the same family | How much the alias moves relative to the snapshot |
| Control | An open-weights model with a fixed weight hash, served by one provider | Infrastructure and provider noise with the weights held constant |

Panel at first run: the current mid-tier snapshot and its alias from each of Anthropic,
OpenAI and Google, plus one open-weights control. Frontier-tier models are excluded from
the monthly run on cost; one frontier snapshot per vendor is run once a quarter if budget
allows (see section 6). Model identifiers are chosen on the day of the first run from each
vendor's current list and recorded in `drift/panel.yaml` with the date. **The panel is part
of the data, not a configuration to tune.** When a vendor retires an identifier, the runner
keeps calling it until the vendor returns an error, and the error is recorded as the result.

### 2.3 Everything held fixed

- Temperature 0, fixed `max_tokens`, fixed system prompt, no tools, no vendor-side
  caching or "prompt caching" features.
- One pinned HTTP client and pinned API version headers per vendor, raw HTTP rather than
  vendor SDKs, so an SDK release cannot change the request. The calls go through the
  portfolio's gateway library (project 04, version 0) in **pass-through mode**: raw
  request recorded, no retries, no caching, no rewriting. The gateway supplies telemetry
  and the cost ledger; it is never allowed to become a confound in the record.
- Same runner (GitHub-hosted Actions runner, `ubuntu-latest` pinned to a specific image
  version), same region as far as GitHub allows, same time of day.
- Request and response headers stored with every call: request identifiers, any model or
  version header the vendor returns, rate-limit headers.
- The suite is content-hashed. The hash is printed in every report. Any change to an item
  creates suite v2, which is run alongside v1 for one bridging month.
- Development caching is banned on the monthly run. Caching is for building the graders,
  never for the record.

### 2.4 Same-day repeats

Each item is sent k = 5 times per model per run, in shuffled order, spaced across the run.
This yields the same-day flip rate (noise floor) and the output stability figure. Five is
the smallest k that gives a usable per-item disagreement estimate; the cost is carried by
keeping the suite small (section 3).

### 2.5 Held-out items against contamination

Half of the hand-written items are **held out**: their SHA-256 hashes are committed on day
one, the items themselves are not published until month 12. If public items drift toward
"correct" while held-out items do not, that is evidence of training-set contamination
rather than capability change, and it is reported as such. The public half exists so that
anyone can reproduce the public part of the record immediately.

## 3. The suite (v1)

Roughly 420 items, all programmatically graded. Sizes are targets; the final count is
fixed at freeze and printed in the first report.

| Block | Items | Source | Grader | What drift here means |
|---|---:|---|---|---|
| Closed-form reasoning | 120 | Fixed-seed sample from GSM8K test and MATH (levels 1-3), answer-only format | Numeric match with tolerance | Capability change |
| Multiple choice knowledge | 100 | Fixed-seed sample from MMLU test across 10 subjects, ARC-Challenge | Letter match | Capability change or answer-format change |
| Instruction following | 60 | IFEval-style verifiable constraints, half hand-written | Constraint checker (length, keywords, JSON validity, casing, structure) | Compliance and formatting change |
| Structured extraction | 40 | Hand-written passages with a JSON schema, half held out | Schema validation plus field exact match | Formatting, hallucinated fields |
| Refusal calibration | 40 | 20 benign requests that sound sensitive and must be answered; 20 requests that any vendor policy refuses and must be refused. All items are innocuous to publish | Refusal classifier by regex plus answered/not-answered check | Safety tuning shifts in both directions |
| Long-context recall | 20 | 8k-token passages with one planted fact, question at the end | Exact match | Context handling change |
| Paraphrase robustness | 40 | 20 reasoning items above, each in 2 paraphrases | Same as parent item | Sensitivity to wording; a large gap is itself a finding |

Notes:

- Public benchmark items are sampled once with a recorded seed and then frozen as files
  in the repo; the benchmark loaders are never called again.
- Hand-written items (about 90 of the 420) are the time cost of this phase: roughly two
  evenings. Write them plainly, grade them twice by hand before freeze.
- Every item carries: `id`, `block`, `prompt`, `system`, `grader`, `expected`,
  `held_out` flag, `source`, `licence`.

## 4. Statistics

- **Accuracy CI:** percentile bootstrap over items, 2,000 resamples, reported as
  point estimate with 95% interval. Never a bare percentage.
- **Month-over-month change:** paired by item, McNemar's test on correct/incorrect
  flips, alongside the flip rate and its CI. Reported per model, per block.
- **Drift call:** as defined in section 1, flip rate against the same-day noise floor.
  Both numbers are always shown next to each other.
- **Detectable effect:** with about 300 gradeable items and a paired design, a change
  of roughly five accuracy points is detectable at 80% power for a model near 80%
  accuracy. The exact figure is computed from the observed same-day disagreement after
  the first two runs and published in the October report. Smaller changes are reported
  but not called drift.
- **Twelve-month view:** per model, a time series of accuracy with intervals, cumulative
  flip count, refusal rate, latency, and cost. Snapshot and alias arms overlaid.
- **Control arm:** the open-weights model's month-over-month flip rate is the
  infrastructure noise estimate; a vendor model is only called drifting if it also
  exceeds the control arm's flip rate that month.

## 5. Infrastructure

- **Runner:** GitHub Actions, `schedule` cron on the 1st of each month at 06:00 UTC
  (GitHub cron can slip by up to an hour; the actual start time is recorded), plus
  `workflow_dispatch` for manual runs. No VPS involved. If a scheduled run fails, one
  rerun is allowed within 72 hours and is marked as a rerun in the record.
- **Secrets:** vendor keys in GitHub Actions secrets. Hard spend caps set in every
  vendor console before the first dry run (portfolio action 3). The `boundary` library is
  installed from its private repository with a fine-grained GitHub token, read-only and
  scoped to that one repository, held as an Actions secret (04 stays private at `v0.1.0`,
  decided 2026-09-07). The runner also carries
  its own cap: it aborts and records a partial run if spend passes 150% of the expected
  cost for that run.
- **Storage:** raw request and response for every call as JSONL, one file per model per
  run, committed to the repo under `drift/runs/YYYY-MM/`. Roughly 2,000 calls per model
  per run at a few KB each: tens of MB per month, fine for git; moved to Git LFS or
  release assets if it grows past that.
- **Reports:** the job renders `drift/reports/YYYY-MM.md` (tables and one SVG chart per
  model) and updates the results table in the README. The dashboard is phase 2.
- **Reproducibility:** `uv run drift --month 2026-10 --replay` regrades from stored
  responses without calling any vendor, so anyone can verify the numbers.
- **Code:** Python 3.13, `httpx`, `pydantic`, `polars`, `duckdb` for analysis,
  `typer` for the CLI. Typed, `ruff` and `mypy` clean, tests for every grader against
  hand-written fixtures including adversarial outputs (markdown fences, trailing text,
  unicode digits).

Layout:

```
drift/
  suite/v1/           frozen items, one JSONL per block, plus SUITE_HASH
  suite/heldout/      hashes only until month 12
  panel.yaml          model identifiers, arms, provider, date chosen
  runner/             call, retry, record
  graders/            one module per grader type, fully tested
  analysis/           bootstrap, McNemar, drift call, report rendering
  runs/YYYY-MM/       raw JSONL per model
  reports/YYYY-MM.md  rendered monthly report
.github/workflows/drift.yml
```

## 6. Cost

Assumptions, to be replaced with the price list on the day of the first run:

| Quantity | Value |
|---|---|
| Items | 420 |
| Repeats | 5 |
| Calls per model per run | 2,100 |
| Average tokens per call | ~700 in (long-context block raises the mean), ~150 out |
| Models per run | 7 (3 snapshot + 3 alias + 1 control) |
| Tokens per run | ~10M in, ~2M out |
| Blended mid-tier price | ~US$0.50 per M in, ~US$2 per M out |
| Estimated cost per run | ~US$9, about **CA$12** |

Against the CA$35 per month line for drift runs, that leaves headroom for one of:
a quarterly frontier-tier pass (three snapshots, one repeat, roughly CA$20), or doubling
the suite in v2. Decide after the first two runs when the real bill is known. Record the
actual invoice in the portfolio's STATUS next to the estimate.

If the first dry run shows the estimate is off by more than 2x, cut k to 3 before cutting
items.

## 7. Schedule to first run

| Date | Step | Output |
|---|---|---|
| Sep 8 - 12 | Repo scaffold, item schema, grader modules with tests | `drift/graders` green in CI |
| Sep 12 - 16 | Sample and freeze public items; write 90 hand-written items; grade by hand twice | `drift/suite/v1` and `SUITE_HASH` committed; held-out hashes committed |
| Sep 16 - 19 | Runner with raw HTTP per vendor, retry policy, spend cap, JSONL recording | Dry run on 20 items, 1 repeat, all arms |
| Sep 19 - 21 | Analysis and report rendering; regrade-from-store path | Report renders from the dry run |
| Sep 22 - 24 | Full dry run (all items, k = 5) after vendor caps are set | Cost check against section 6; fix graders that misfire |
| **Sep 27 (Sun)** | **First official run, suite v1 frozen** | `runs/2026-09`, `reports/2026-09.md` |
| **Oct 1** | Second official run, four days later | Short-interval noise baseline between two full runs |
| Nov 1 onward | Monthly on the 1st | Twelve months by Sep 2027 |

The Sep 27 and Oct 1 pair is deliberate: two full runs four days apart give a between-run
noise estimate before any vendor has had time to change anything, which anchors every
drift call that follows.

Effort: about 25 hours across three weeks, alongside the start of project 01.

## 8. Risks

| Risk | Handling |
|---|---|
| Vendor retires a snapshot mid-year | Keep calling; the error is the data. Add the successor snapshot as a new arm the same month so the family's series continues |
| API shape or auth changes | Raw HTTP with pinned version headers; a failed month is recorded as a failed month, then fixed |
| Rate limits during the run | Spread calls over the run window, exponential backoff, record every retry |
| Cost overrun | Console caps plus the runner's 150% abort. First two runs at k = 5 decide whether k stays |
| GitHub cron slips or skips | Record actual start time; `workflow_dispatch` rerun within 72 hours, marked |
| Contamination of public items | Held-out half with committed hashes; report public and held-out separately |
| Grader bugs discovered later | Regrade from stored raw responses; graders are versioned and every report states the grader version |
| Refusal probes misread as adversarial | Every probe is benign to publish; the "must refuse" set is limited to requests every vendor policy already refuses. Review the set once before freeze |
| Temptation to fix the suite when a result looks wrong | The suite is frozen. A wrong-looking result is a finding. Changes go to v2 with a bridging month |

## 9. What this deliberately does not do

- No open-ended generation quality. That needs a calibrated judge and belongs to phase 2.
- No frontier-tier models monthly. Cost. Quarterly at most.
- No agentic or tool-use evaluation. Different failure modes, different project (10).
- No attempt to explain why a vendor changed something. The record shows that and when;
  the why is theirs.

## 10. Rule C candidates: what is expected not to work

To be tested during the dry runs and documented with evidence, whichever fails:

1. **LLM-as-judge for drift.** Run a judge over 50 items alongside the programmatic
   grader for one dry run and show the judge's own repeat disagreement. Expected: the
   judge's noise floor is higher than the effect being measured.
2. **Public benchmark items alone.** Expected: contamination makes them drift upward
   without capability change; the held-out half is the control.
3. **k = 1, no repeats.** Expected: every month looks like drift. The Sep 27 and Oct 1
   pair will show it.

## 11. Definition of done for phase 1

- [ ] Suite v1 frozen, hash committed, held-out hashes committed
- [ ] Panel recorded with dated identifiers and arms
- [ ] Every grader tested against adversarial fixtures
- [ ] First official run committed with raw responses and a rendered report, by 2026-09-30
- [ ] Oct 1 run committed; noise floor and detectable effect published in the October report
- [ ] Workflow scheduled for the 1st of each month, with manual rerun path documented
- [ ] Regrade-from-store reproduces the published numbers
- [ ] README results table updates from the job
- [ ] Actual cost of the first two runs recorded against the estimate
- [ ] One Rule C item documented with evidence


---

# Part B. The release gate

**Build window:** 8 weeks, 2026-12-01 to 2027-01-31, evenings and weekends, across the
holidays. Depends on `mselect` v0.1.0 from project 02 (due Nov 29) and on the shared VPS
(portfolio action 2b) by week 6.

## B1. What this produces

No prompt or model change reaches users unless it is proven not to have regressed: the
discipline a test suite gives code, applied to AI, with an audit trail a regulator can
read. The claim "we built an eval" is table stakes; the claim this project makes is "our
eval is trustworthy", and every part of it is measured.

The numbers a stranger can check:

| Measure | What it shows |
|---|---|
| Judge agreement with human gold labels: Cohen's kappa and Krippendorff's alpha, per task, with bootstrap CI | Whether the LLM judge is measuring anything. An uncalibrated judge is a random number generator with good manners |
| Judge sensitivity and specificity, and the corrected pass rate they imply | The score after the judge's own error is accounted for, next to the raw score most teams report |
| Every eval score with a 95% bootstrap CI | No bare percentages anywhere in the system |
| Items needed to detect a 1-, 3- and 5-point regression at 80% power, per suite | From project 02's power function, validated empirically here |
| Gate false-block rate from A/A runs (same prompt, same model, twice) | How often the gate blocks a change that changed nothing. The gate is useless if this is high |
| Gate decisions on a real repository: passed, blocked, with reasons, over the build | The gate working, not described |
| Red-team pass rates (PII leakage, prompt injection, jailbreak, over-refusal) with CIs, per model and prompt version | The safety suites as numbers |
| Cost and latency per eval run, per model, per prompt version | What the gate costs to operate |
| Twelve months of drift data on the dashboard (four months by the end of phase B) | The record from Part A, live |

## B2. Design decisions

### B2.1 One library, three surfaces

A single Python package `gate` does the work. Three thin surfaces sit on it: a CLI for
local runs, a GitHub Action for pull requests, and a FastAPI service for the dashboard.
Nothing lives only in the service; everything the dashboard shows can be reproduced from
the CLI and the stored runs.

### B2.2 Non-inferiority, not "is it better"

The gate question is "did it get worse by more than we tolerate", so the test is
one-sided non-inferiority on the paired per-item difference: the candidate fails when the
lower bound of the 95% bootstrap interval for (candidate minus baseline) is below minus
delta. Delta defaults to 3 accuracy points and is set per suite in the eval spec. Paired
by item, always, because items differ far more than prompts do and an unpaired test
throws that away.

### B2.3 The judge is an instrument and gets calibrated like one

Any LLM-as-judge used by the gate is first run against a human-labelled gold set. The
gate stores the judge's kappa, alpha, sensitivity and specificity and uses them to
correct the pass rate it reports (Rogan-Gladen correction with an interval that
propagates the calibration uncertainty). A judge below kappa 0.6 on a task is refused for
that task, and the gate falls back to a programmatic grader or to "needs human review".

### B2.4 Audit trail by construction

Every run appends one record to a ledger: content hashes of the suite, the prompt
version, the model identifiers and request settings, the grader versions, the raw
responses file, the statistics, and the decision with its reasons. Reports and model
cards reference those hashes. Nothing in the ledger is ever edited; a mistake is
corrected by a new record that references the old one. This is what "an audit trail a
regulator can read" means concretely.

### B2.5 Reuse over novelty

The runner, storage and programmatic graders are the ones from Part A, and every model
call goes through the portfolio gateway (project 04) so cost and latency land in the
shared ledger. The statistics use project 02's `mselect` for the power function and item
parameters. Presidio does PII
detection. OpenTelemetry does tracing. The project earns attention through statistical
rigour, not through a new eval framework, and the write-up says so.

## B3. Architecture

```
gate/
  spec/         eval spec (YAML): suites, items, graders, judge config, delta, min items
  items/        loaders: programmatic suites (shared with drift/), red-team suites, gold sets
  graders/      programmatic graders (from drift/), judge grader, Presidio PII grader
  judge/        rubric prompts, calibration (kappa, alpha, sens/spec), bias checks, correction
  runner/       vendor calls (raw HTTP, from drift/), dev cache, cost and latency capture
  stats/        bootstrap, paired non-inferiority, McNemar, A/A false-block study, power (via mselect)
  decision/     verdict with reasons; multiple-suite handling (Holm)
  ledger/       append-only run records, content hashes, DuckDB + Parquet
  report/       eval report and model card (Markdown + JSON), PR comment renderer
  cli.py        gate run, gate compare, gate calibrate-judge, gate aa, gate report, gate serve
action/         composite GitHub Action: checkout, gate compare base..head, comment, exit code
service/        FastAPI: read-only API over the ledger and drift/runs; static dashboard
deploy/         docker compose for the VPS: service, Caddy for TLS at gate.peterparker.ca
docs/
  judge-calibration.md   the gold set, the raters, the numbers
  gate-statistics.md     the non-inferiority test, delta, power, false-block rate
  rejected.md            Rule C
  writeup.md             "your LLM eval has no error bars"
```

Storage: one DuckDB file per project plus Parquet under `runs/`. The drift record from
Part A is read in place. Tracing: every vendor call and every grader call emits an
OpenTelemetry span; the collector runs in the compose stack and traces are retained for
30 days. Frontend: server-rendered pages with a small charting library, no build step, so
the dashboard stays cheap to maintain.

## B4. Judge calibration

**Domain:** consumer questions answered from public financial-regulator guidance
(Financial Consumer Agency of Canada pages, SEC investor bulletins). Public, regulated,
nothing to do with the employer, and the kind of content where an unsupported claim
matters.

**Task:** given a source document and a model's answer to a consumer question, judge (a)
faithfulness: every claim in the answer is supported by the source, and (b) completeness:
the answer addresses the question. Each is a binary label with a one-line justification.

**Gold set:** 300 answer instances, generated by three models of different sizes over 100
questions, so the set contains real failures. Labelled by hand against a written rubric.
Labelling budget is one week of evenings; the project file already warns this is the
hidden cost.

**Reliability of the gold set itself:** 100 of the 300 are re-labelled by the same rater
two weeks later for intra-rater agreement. A second rater labels the same 100 if one is
available (not a colleague from work). Both agreements are reported; if the second rater
is not available, the write-up says the gold set is single-rater and treats that as a
limitation.

**Judges:** two, a small model and a mid-tier model, each with the same rubric prompt.
For each: kappa and alpha against gold with bootstrap CIs; sensitivity and specificity;
test-retest across two runs; a position-swap check on paired items to detect order bias;
a verbosity check (does answer length predict the judge's label after controlling for the
gold label). The cheaper judge is kept if it clears kappa 0.6; otherwise the mid-tier one.

**Correction:** reported pass rates are the raw judge rate and the corrected rate
(Rogan-Gladen) with an interval that includes calibration uncertainty. Both appear in
every report so the reader sees the gap.

## B5. Gate statistics

- **Minimum items per suite** from `mselect.power.items_needed(delta, 0.8, ability)`,
  with ability set from the baseline's score. A suite below its minimum reports "under-
  powered" and the gate does not block on it; it warns.
- **Paired non-inferiority** as in B2.2, percentile bootstrap with 2,000 resamples over
  items, plus McNemar on the flips for binary suites as a second opinion.
- **Several suites at once:** Holm correction across suites for the block decision; each
  suite's own interval is still shown uncorrected, labelled as such.
- **False-block rate:** an A/A study runs the same prompt and model as both baseline and
  candidate 50 times on each suite; the share of blocks is the false-block rate and is
  reported with an interval. Target under 5%. If the observed rate is higher, the cause
  is same-day nondeterminism, which Part A measures, and delta or the repeat count is
  adjusted with the reasoning recorded.
- **Cost and latency regressions:** separate thresholds in the spec; a candidate that is
  equally accurate but twice as slow or expensive fails on that line, clearly labelled.

## B6. The GitHub Action

A composite action `gate-action` for repositories that hold prompts or model
configuration:

1. On pull request, determine the baseline (the default branch's prompt version and model)
   and the candidate (the PR's).
2. Run `gate compare` on the suites named in the repository's `gate.yaml`, using the
   development cache so unchanged items cost nothing.
3. Post one PR comment: a table per suite with baseline, candidate, difference and its
   interval, the verdict, and the corrected judge rate where a judge is involved.
4. Exit non-zero on a block, so branch protection can require the check.

It is exercised on a **demo repository** that holds a real prompt for the regulated Q&A
task, with a history of at least ten pull requests over the build: some that pass, some
that are blocked, one A/A pair, and one that fails only on latency. The PR history is the
evidence that the gate works.

## B7. Red-team suites

All items come from published, public sources; nothing here is novel adversarial content.

| Suite | Items | Grader | Reported |
|---|---:|---|---|
| PII leakage | 200 prompts with synthetic personal data in context and an instruction not to reveal it | Presidio detects any PII entity in the output | Leak rate with CI |
| Prompt injection | 200 items from public injection corpora, embedded in a retrieval-style context | Programmatic: did the injected instruction's marker appear | Injection success rate with CI |
| Jailbreak | 150 items from a published benchmark's behaviour list, using only its already-public prompts | Refusal classifier (regex plus the calibrated judge for ambiguous cases) | Compliance rate with CI |
| Over-refusal | 150 benign prompts that superficially resemble unsafe ones, from a published set | Same refusal classifier | Over-refusal rate with CI |

The refusal classifier is itself calibrated against 100 hand labels, and its kappa is
reported. The two refusal suites together give refusal calibration: a model that refuses
everything passes jailbreak and fails over-refusal, and both numbers are shown side by
side so that trade is visible.

## B8. Dashboard and deployment

- `gate.peterparker.ca` on the shared VPS, docker compose: the FastAPI service, Caddy
  for TLS, the OpenTelemetry collector. Read-only, no accounts.
- Pages: drift record (per model and arm, accuracy with intervals, flip rates, refusal
  rates, cost, latency, month by month); gate history for the demo repository; judge
  calibration figures; red-team results per model.
- The service reads the ledger and `drift/runs` from a nightly `git pull`; it never
  writes. If the VPS is down, nothing is lost and the CLI still reproduces every number.
- Uptime is monitored by a free external ping; the drift job does not depend on the VPS
  at all.

## B9. Reuse by projects 04, 05, 06 and 10

`gate` ships as a package with a documented adapter: a project provides an eval spec and
an item loader, and gets the statistics, the judge calibration, the ledger and the report
for free. Each of the four downstream READMEs states "measured with the AI Release Gate"
and links here. The adapter is written in week 8 and exercised against project 04's
first suite in February 2027, which is the first real test of the reuse claim.

## B10. Week by week

| Week | Dates | Build | Done when |
|---|---|---|---|
| 1 | Dec 1 - 7 | `gate` scaffold; eval spec; ledger; runner and graders lifted from `drift/`; `mselect` wired in; A/A harness | `gate run` and `gate aa` work on a Part A block; first false-block estimate |
| 2 | Dec 8 - 14 | Gold set: questions, source documents, three models' answers; rubric written; labelling begins; judge runner and rubric prompts | 300 instances generated; 150 labelled |
| 3 | Dec 15 - 21 | Labelling finished; judge calibration for two judges; bias checks; correction implemented | `docs/judge-calibration.md` with kappa, alpha, sensitivity, specificity |
| 4 | Dec 22 - 28 | GitHub Action; demo repository; first gated pull requests. Holiday week, kept light | Three PRs with gate comments, one blocked |
| 5 | Dec 29 - Jan 4 | Red-team suites and Presidio grader; refusal classifier calibrated | Four suites reporting with intervals |
| 6 | Jan 5 - 11 | VPS stood up; compose stack; service and dashboard; drift record ingested; `gate.peterparker.ca` live; OpenTelemetry | Dashboard shows the Part A record and the demo repo's gate history |
| 7 | Jan 12 - 18 | Eval reports and model cards generated from the ledger; cost and latency lines; A/A study at full size; intra-rater re-labelling of 100 gold items | False-block rate published; reports render for every run |
| 8 | Jan 19 - 31 | Adapter for downstream projects; `docs/rejected.md`; write-up "your LLM eval has no error bars"; README to Rule A shape; v0.1.0; repository public | Definition of done all checked |

Slack: the second judge in week 3 and the verbosity check are the first things to drop.
The dashboard is kept plain on purpose; if week 6 runs long, the pages ship as static
Markdown rendered by the service rather than charts.

## B11. Cost

Phase B draws on the CA$540 line together with Part A's drift runs (about CA$420 over the
year). Anthropic list prices at the plan date (per million tokens): Haiku 4.5 $1 in and $5
out, Sonnet 5 $2 in and $10 out, Opus 5 $5 in and $25 out; batch endpoint at half. Other
vendors assumed comparable and checked before the first run.

| Line | Calls | Estimate |
|---|---:|---:|
| Gold set generation, 3 models, 100 questions | 300 | ~US$2 |
| Judge calibration, 2 judges, 300 items, 2 repeats, plus swaps | ~1,800 | ~US$6 |
| Demo repository gate runs, ~10 PRs, cached where unchanged | ~4,000 | ~US$8 |
| Red-team suites, 700 items, 4 models | ~2,800 | ~US$6 |
| A/A study, 50 pairs per suite on cached baselines | ~3,000 | ~US$5 |
| Development margin | | ~US$10 |
| **Phase B API total** | | **~US$37, about CA$50** |
| VPS share for phase B (2 of 12 months of the CA$300 line) | | ~CA$50 |

Well inside the line. Actual invoices go next to the estimate in the portfolio's STATUS.

## B12. Risks

| Risk | Handling |
|---|---|
| Gold-set labelling takes longer than a week | It is the critical path in weeks 2 and 3. Keep the set at 300 and well-chosen; a smaller clean set beats a larger sloppy one. Intra-rater re-labelling in week 7 catches drift in the rater |
| Single-rater gold set | Reported as a limitation; second rater sought outside work; intra-rater agreement published either way |
| Judge below kappa 0.6 on a task | That is a finding, published. The gate refuses the judge for that task and uses programmatic grading or flags for human review |
| Holidays in weeks 4 and 5 | Those weeks carry the two most self-contained pieces (the Action, the red-team suites) and have slack built in |
| VPS not ready by week 6 | The dashboard can run locally and be shown as static exports for a week; the drift job is unaffected. Action 2b in the portfolio STATUS tracks it |
| Scope sprawl into a general eval framework | The eval spec stays small. Anything not needed by the demo repository or a downstream project is not built |
| Vendor changes a judge model mid-build | Judges are pinned by dated identifier; a change means recalibration, which is a one-command rerun on the gold set |
| Red-team suites misread as adversarial research | Public items only, from published benchmarks; documented in the README |
| `mselect` late from project 02 | The power function has a simple fallback (normal approximation on the binomial) that is swapped for `mselect` when it lands; the interface is fixed in week 1 |

## B13. Rule C candidates: what is expected not to work

1. **Uncalibrated judge percentages.** Report the raw judge pass rate next to the
   corrected one on the same runs; the expected gap of several points is the argument.
2. **Gating on the point estimate.** Run the A/A study with a "block if candidate is
   lower" rule; expected false-block rate near 50%, against under 5% for the interval
   rule.
3. **Pairwise preference judging instead of an absolute rubric.** Expected: strong
   position bias in the swap check, which the absolute rubric with position-fixed
   rendering avoids.

## B14. Definition of done (whole project)

Mirrors the portfolio's definition:

- [ ] Drift runs executing monthly since Sep 2026, data published (Part A)
- [ ] Judge calibrated against human labels, kappa and alpha reported with CIs
- [ ] Corrected pass rates reported next to raw
- [ ] Every reported score carries a bootstrap CI
- [ ] Power analysis published: items needed per effect size, from `mselect`, validated
- [ ] False-block rate published from the A/A study
- [ ] GitHub Action gating a real repository, with a PR history showing passes and blocks
- [ ] Red-team suites (PII, injection, jailbreak, over-refusal) passing and reported
- [ ] Append-only ledger; every report references content hashes
- [ ] Live dashboard at gate.peterparker.ca, stable, showing the drift record
- [ ] Adapter documented; project 04 measured with it in Feb 2027
- [ ] Write-up published
- [ ] One rejected approach documented with evidence
- [ ] v0.1.0 tagged; repository public

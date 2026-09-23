"""Command line: gate run | compare | aa | power | spec | gold | judge.

Stage 1 (PLAN.md B10): every side comes from Part A's stored records, so `run`, `compare`,
`aa` and `power` call no vendor and spend nothing. A side is named `MONTH/ARM`, optionally
`MONTH/ARM@0,1` to keep only those repeats.

Stage 2 adds `gold` and `judge`. Of those only `judge run` makes a vendor call, and it refuses
to unless `--i-am-allowed-to-call-vendors` is passed, because this laptop sits behind a TLS
inspection proxy on the work network and a vendor call from it is a call through somebody
else's middlebox (CLAUDE.md). `gold label` and `judge calibrate` are offline.
"""

from __future__ import annotations

import shutil
import textwrap
from collections.abc import Collection
from pathlib import Path
from typing import Annotated

import typer

from drift.panel import Arm, Panel, load_panel
from drift.runner.records import arms_recorded, read_records, records_path
from gate import __version__, aa, distractors, generate, gold, ledger, report
from gate import sources as gold_sources
from gate.decision import decide
from gate.judge import calibration as calib
from gate.judge import report as judge_report
from gate.judge import runner as judge_runner
from gate.judge.rubric import UNANSWERABLE_NOTE
from gate.outcomes import NoSuchArmError, Side, part_a_side
from gate.spec import EvalSpec, load_spec
from gate.stats import PowerLine, items_needed

app = typer.Typer(add_completion=False, help=f"gate {__version__}: the release gate")
spec_app = typer.Typer(help="the eval spec")
gold_app = typer.Typer(help="the human-labelled gold set the judge is calibrated against")
judge_app = typer.Typer(help="the LLM judge, and the calibration that decides if it may be used")
app.add_typer(spec_app, name="spec")
app.add_typer(gold_app, name="gold")
app.add_typer(judge_app, name="judge")

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "drift" / "runs"
SPECS = ROOT / "gate" / "specs"
DEFAULT_SPEC = SPECS / "drift-blocks.yaml"
LEDGER = ROOT / "gate" / "runs" / ledger.LEDGER_FILE
GOLD = ROOT / "gate" / "gold"
DOCS = ROOT / "docs"
SOURCE_LIST = SPECS / "gold-sources.yaml"
ANSWER_PANEL = SPECS / "gold-answers.yaml"
JUDGE_PANEL = SPECS / "gold-judges.yaml"
BOUNDARY_CONFIG = ROOT / "drift" / "config" / "boundary.yaml"
PROJECT = "ai-release-gate"

# Every command that spends money asks for this, spelled out rather than a bare --yes. This
# laptop is behind a TLS inspection proxy on the work network, so a vendor call from it goes
# through somebody else's middlebox (CLAUDE.md). These commands are meant to run in CI.
VENDOR_FLAG = "--i-am-allowed-to-call-vendors"
VENDOR_HELP = "confirm this machine and network may call vendors; CI passes it"

SpecOpt = Annotated[Path, typer.Option(help="the eval spec (YAML)")]
SIDE_HELP = "MONTH/ARM, or MONTH/ARM@0,1 to keep only those repeats"


def _spec(path: Path) -> EvalSpec:
    try:
        return load_spec(path)
    except (OSError, ValueError) as e:
        typer.echo(f"spec {path}: {e}", err=True)
        raise typer.Exit(2) from e


def _parse_side(text: str) -> tuple[str, str, Collection[int] | None]:
    repeats: Collection[int] | None = None
    if "@" in text:
        text, reps = text.split("@", 1)
        try:
            repeats = sorted({int(k) for k in reps.split(",") if k})
        except ValueError as e:
            typer.echo(f"repeats must be integers: {reps!r}", err=True)
            raise typer.Exit(2) from e
    if "/" not in text:
        typer.echo(f"a side is {SIDE_HELP}, not {text!r}", err=True)
        raise typer.Exit(2)
    month, arm = text.split("/", 1)
    return month, arm, repeats


def _side(spec: EvalSpec, text: str) -> Side:
    month, arm, repeats = _parse_side(text)
    try:
        return part_a_side(RUNS, spec, month=month, arm=arm, repeats=repeats)
    except NoSuchArmError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e


def _write(out: Path | None, text: str) -> None:
    typer.echo(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8", newline="\n")
        typer.echo(f"written to {out}", err=True)


@spec_app.command("show")
def spec_show(spec: SpecOpt = DEFAULT_SPEC) -> None:
    """Validate a spec and print it with its content hash."""
    s = _spec(spec)
    typer.echo(f"{s.name}  sha256 {s.sha256()}")
    typer.echo(f"delta {s.delta_points:g} points, alpha {s.alpha}, {s.resamples} resamples")
    for su in s.suites:
        extra = f", benchmark {su.benchmark}" if su.benchmark else ""
        typer.echo(
            f"  {su.key}: {su.source.kind} {su.source.block}"
            f"{' (held out)' if su.source.held_out else ''}{extra}"
        )


@app.command("run")
def run(
    side: Annotated[str, typer.Argument(help=SIDE_HELP)],
    spec: SpecOpt = DEFAULT_SPEC,
    out: Annotated[Path | None, typer.Option(help="also write the table here")] = None,
) -> None:
    """Score one side: every suite's accuracy with its interval."""
    s = _spec(spec)
    _write(out, report.render_side(_side(s, side), resamples=s.resamples, seed=s.seed))


@app.command("compare")
def compare(
    baseline: Annotated[str, typer.Option(help=SIDE_HELP)],
    candidate: Annotated[str, typer.Option(help=SIDE_HELP)],
    spec: SpecOpt = DEFAULT_SPEC,
    out: Annotated[Path | None, typer.Option(help="also write the report here")] = None,
    record: Annotated[bool, typer.Option(help="append the decision to the ledger")] = True,
    supersedes: Annotated[str | None, typer.Option(help="ledger record this one corrects")] = None,
) -> None:
    """The gate: is the candidate non-inferior to the baseline? Exit 1 on a block."""
    s = _spec(spec)
    base, cand = _side(s, baseline), _side(s, candidate)
    d = decide(s, base, cand)
    _write(out, report.render_decision(d))
    if record:
        rec = ledger.record_for(
            d, baseline=dict(base.source), candidate=dict(cand.source), supersedes=supersedes
        )
        ledger.append(LEDGER, rec)
        typer.echo(f"ledger record {rec.record_id} appended to {LEDGER}", err=True)
    if d.blocked:
        raise typer.Exit(1)


@app.command("aa")
def aa_study(
    month: Annotated[str, typer.Option(help="the run to cut within-run pairs from")],
    baseline: Annotated[
        str, typer.Option(help="a second run of the same arms, for between-run pairs")
    ] = "",
    size: Annotated[int, typer.Option(help="repeats per side in a within-run pair")] = 2,
    spec: SpecOpt = DEFAULT_SPEC,
    out: Annotated[Path | None, typer.Option(help="also write the report here")] = None,
    within: Annotated[bool, typer.Option(help="include within-run pairs")] = True,
    delta: Annotated[
        list[float] | None,
        typer.Option(help="other margins, in points, to run the same pairs at as well"),
    ] = None,
    decide_all: Annotated[
        bool, typer.Option(help="also run with the power screen off, every suite decided")
    ] = True,
) -> None:
    """The A/A study: the gate against itself, and the false-block rate that comes out."""
    s = _spec(spec)
    cur = {k: list(read_records(records_path(RUNS, month, k))) for k in arms_recorded(RUNS, month)}
    if not cur:
        typer.echo(f"no records for {month!r}", err=True)
        raise typer.Exit(2)
    pairs: list[aa.Pair] = []
    if within:
        pairs += aa.within_run_pairs(s, cur, month=month, size=size)
    if baseline:
        prev = {
            k: list(read_records(records_path(RUNS, baseline, k)))
            for k in arms_recorded(RUNS, baseline)
        }
        if not prev:
            typer.echo(f"no records for {baseline!r}", err=True)
            raise typer.Exit(2)
        pairs += aa.between_run_pairs(s, prev, cur, first_month=baseline, second_month=month)
    if not pairs:
        typer.echo("nothing to pair: turn within-run pairs on or name a baseline run", err=True)
        raise typer.Exit(2)
    settings: list[tuple[str, EvalSpec]] = [(f"delta {s.delta_points:g}, as specified", s)]
    if decide_all:
        settings.append(
            (f"delta {s.delta_points:g}, every suite decided", s.deciding_every_suite())
        )
    for d in delta or []:
        alt = s.with_delta(d)
        settings.append((f"delta {d:g}, as specified", alt))
        if decide_all:
            settings.append((f"delta {d:g}, every suite decided", alt.deciding_every_suite()))
    studies: list[tuple[str, aa.AAStudy]] = []
    for label, sp in settings:
        typer.echo(f"running {len(pairs)} pairs: {label}", err=True)
        studies.append((label, aa.study(sp, pairs)))
    _write(out, report.render_aa(studies, seed=s.seed))


@app.command("power")
def power(
    side: Annotated[
        str, typer.Option(help="the baseline whose scores set the ability, " + SIDE_HELP)
    ],
    spec: SpecOpt = DEFAULT_SPEC,
) -> None:
    """Items needed per suite to see a 1, 3 and 5 point drop, from project 02's bank."""
    s = _spec(spec)
    base = _side(s, side)
    lines: list[tuple[str, int, list[PowerLine]]] = []
    for su in s.suites:
        so = base.suites[su.key]
        acc = so.accuracy(resamples=s.resamples, seed=s.seed)
        pls = [
            items_needed(
                e,
                power=s.power.target,
                accuracy=acc.point if acc.n else None,
                reference_ability=s.power.reference_ability,
            )
            for e in s.power.effect_points
        ]
        lines.append((su.key, so.items, pls))
    typer.echo(report.render_power(lines))


# ---------------------------------------------------------------------------- the gold set


def _gold_or_exit() -> gold.GoldSet:
    g = gold.load(GOLD)
    if not g.instances:
        typer.echo(
            f"no answer instances in {GOLD / gold.INSTANCES_FILE}. The gold set is generated by "
            "`gate gold generate`, which makes vendor calls and so runs in CI, not here.",
            err=True,
        )
        raise typer.Exit(2)
    problems = g.problems()
    if problems:
        for p in problems:
            typer.echo(f"gold set problem: {p}", err=True)
        raise typer.Exit(2)
    return g


def _field(label: str, text: str) -> None:
    """One labelled field, whole, wrapped to the terminal.

    Nothing shown to a labeller is ever cut short. The judge is given the entire passage, so a
    labeller shown less is applying the same rubric to less evidence, and the agreement between
    the two would be measuring the truncation rather than the standard. The first version
    stopped at 900 characters with no mark to say it had: every one of the 40 passages is longer
    than that, so every question was answered from a fragment.
    """
    width = max(60, min(shutil.get_terminal_size((100, 24)).columns - 1, 110))
    head = f"  {label:<8}: "
    typer.echo(
        textwrap.fill(text, width=width, initial_indent=head, subsequent_indent=" " * len(head))
    )


def _redo_ids(raw: str) -> list[str]:
    """The instance ids named on --redo. A bare number means the id it obviously means, so
    `--redo 4` and `--redo i-0004` are the same thing, and spaces count as commas."""
    out: list[str] = []
    for token in raw.replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        out.append(f"i-{int(token):04d}" if token.isdigit() else token)
    return out


@gold_app.command("status")
def gold_status() -> None:
    """What the gold set holds and how much of it has been read."""
    typer.echo(gold.summarise(gold.load(GOLD), gold.read_labels(GOLD / gold.LABELS_FILE)))


@gold_app.command("label")
def gold_label(
    pass_no: Annotated[
        int, typer.Option("--pass", help="1 for the full read, 2 for the intra-rater re-read")
    ] = 1,
    limit: Annotated[int, typer.Option(help="stop after this many, 0 for no limit")] = 0,
    redo: Annotated[
        str,
        typer.Option(help="re-read ones already labelled, comma separated: --redo 1,3,4,5"),
    ] = "",
) -> None:
    """Read model answers and judge them against docs/judge-rubric.md. Two keypresses each.

    You never see which model wrote the answer, and you never see what the judge said. Both are
    hidden because a label that reacts to either is not a measurement of either. Resumable:
    stop whenever you like and run the same command again.

    To change your mind about one you have already done, name it on --redo. Labels are
    append-only, so the correction is a new line and the last one wins; nothing is erased.
    """
    import click

    if pass_no not in (1, 2):
        typer.echo("--pass is 1 or 2", err=True)
        raise typer.Exit(2)
    g = _gold_or_exit()
    path = GOLD / gold.LABELS_FILE
    existing = gold.read_labels(path)
    done = gold.latest_labels(existing, pass_no=pass_no)
    instances = g.by_instance

    if pass_no == 1:
        queue = sorted(instances)
    else:
        first = gold.latest_labels(existing, pass_no=1)
        queue = [i for i in gold.intra_rater_sample(sorted(instances)) if i in first]
        if not queue:
            typer.echo("nothing to re-read: the first pass has not labelled the sample yet")
            raise typer.Exit(0)
        # A different order from the first pass, so the second reading is not anchored by the
        # rhythm of the first. Seeded, so stopping and resuming keeps the same order.
        import random as _random

        _random.Random(gold.INTRA_RATER_SEED + 1).shuffle(queue)

    wanted = _redo_ids(redo)
    unknown = [i for i in wanted if i not in instances]
    if unknown:
        typer.echo(f"no such instance: {', '.join(unknown)}", err=True)
        raise typer.Exit(2)
    if wanted:
        in_queue = set(queue)
        todo = [i for i in queue if i in wanted]
        outside = [i for i in wanted if i not in in_queue]
        if outside:
            typer.echo(f"  not in pass {pass_no}'s queue, ignored: {', '.join(outside)}")
        typer.echo(
            f"pass {pass_no}: re-reading {len(todo)}. Your new judgement is appended and the "
            "last one wins; the old line stays in the file."
        )
    else:
        todo = [i for i in queue if i not in done]
        typer.echo(f"pass {pass_no}: {len(queue)} to read, {len(done)} done, {len(todo)} left.")
    typer.echo("  the rubric is docs/judge-rubric.md; read it before the first one\n")
    typer.echo("  FAITHFUL: every claim supported by the source?   y / n")
    typer.echo("  COMPLETE: does it address the question?          y / n")
    typer.echo("  s = skip this one   q = stop (progress saved)")
    typer.echo("  the passage and the answer are always shown whole, never cut\n")

    asked = 0
    for position, instance_id in enumerate(todo, 1):
        if limit and asked >= limit:
            typer.echo(f"stopping at the {limit} you asked for")
            break
        instance = instances[instance_id]
        question = g.by_question[instance.question_id]
        # The document served to the model, which for a d- instance is not the
        # question's own. The labeller must judge against what the model was given.
        source = g.by_source[instance.source_id]
        answer = " ".join(instance.output.split()) or "(the model returned nothing)"
        judgements: list[bool] = []
        stop = skip = False
        while True:
            typer.echo(f"[{position}/{len(todo)}] {instance.id}")
            previous = done.get(instance.id)
            if previous is not None:
                # Your own earlier judgement, which is neither the model's name nor the judge's
                # verdict, so showing it breaks no blind. Without it a correction is made from
                # memory.
                typer.echo(
                    f"  you said: faithful={previous.faithful} complete={previous.complete}"
                    + (f", note {previous.note!r}" if previous.note else "")
                )
            _field("source", source.title)
            _field("passage", " ".join(source.text.split()))
            typer.echo("")
            _field("question", " ".join(question.question.split()))
            if question.unanswerable:
                typer.echo(f"            {UNANSWERABLE_NOTE}")
            _field("expects", "; ".join(question.must_mention))
            if instance.source_id != question.source_id:
                # A distractor: those points are the real answer, taken from a page that is
                # not on screen. Without this the line reads as a claim about the passage.
                typer.echo(
                    "            (from another page, not this one: a correct refusal here is"
                    " faithful but NOT complete)"
                )
            typer.echo("")
            _field("ANSWER", answer)
            if instance.truncated:
                typer.echo("            (cut off at the token budget)")
            for label in ("FAITHFUL", "COMPLETE"):
                typer.echo(f"  {label}? y / n  ")
                ch = click.getchar().lower()
                if ch == "q":
                    stop = True
                    break
                if ch == "s":
                    skip = True
                    break
                if ch not in ("y", "n"):
                    # Only an explicit s skips. Any other key is a slip, and treating a slip as
                    # a skip drops the instance with nothing on screen saying so, which is how
                    # a labelling session quietly loses items.
                    typer.echo("    that is not y, n, s or q; this one again")
                    break
                judgements.append(ch == "y")
            if stop or skip or len(judgements) == 2:
                break
            judgements.clear()
            typer.echo("")
        if stop:
            typer.echo("stopped; run the same command again to carry on")
            break
        if skip or len(judgements) != 2:
            typer.echo("  skipped\n")
            continue
        note = ""
        typer.echo("  n = attach a note, anything else = next")
        if click.getchar().lower() == "n":
            note = typer.prompt("  note").strip()
        gold.append_label(
            path,
            gold.GoldLabel(
                instance_id=instance.id,
                faithful=judgements[0],
                complete=judgements[1],
                note=note,
                output_sha256=instance.output_sha256,
                pass_no=1 if pass_no == 1 else 2,
                labelled_utc=gold.utc_now(),
            ),
        )
        asked += 1
        # Deliberately no running agreement figure here, for the reason Part A's refusal pass
        # gives: a labeller who is told how well they are matching something starts matching it.
        typer.echo(
            f"  recorded: faithful={judgements[0]} complete={judgements[1]} "
            f"({asked} this session)\n"
        )
    typer.echo(f"labels are in {path}")


# ---------------------------------------------------------------------------- the judge


@judge_app.command("prompt")
def judge_prompt_cmd(
    instance_id: Annotated[str, typer.Argument(help="which instance to render, e.g. i-0001")],
    swap: Annotated[
        bool, typer.Option(help="the answer-first ordering used by the bias check")
    ] = False,
) -> None:
    """Print exactly what a judge is shown for one instance. No vendor call."""
    from gate.judge.rubric import judge_prompt

    g = _gold_or_exit()
    instance = g.by_instance.get(instance_id)
    if instance is None:
        typer.echo(f"no instance {instance_id!r}", err=True)
        raise typer.Exit(2)
    question = g.by_question[instance.question_id]
    text = judge_prompt(g.by_source[question.source_id], question, instance.output)
    typer.echo(judge_runner.swap_positions(text) if swap else text)


@judge_app.command("calibrate")
def judge_calibrate(
    judge_key: Annotated[str, typer.Option(help="which judge's verdicts to read")] = "",
    out: Annotated[Path | None, typer.Option(help="write docs/judge-calibration.md here")] = None,
    write_doc: Annotated[bool, typer.Option(help="write docs/judge-calibration.md")] = False,
    seed: int = 0,
) -> None:
    """Kappa, alpha, sensitivity, specificity, self-agreement and order bias, from the record.

    Offline. Reads the stored verdicts and the human labels and computes everything B4 asks
    for; a judge run once can be re-analysed as often as you like for nothing.
    """
    g = _gold_or_exit()
    verdicts = judge_runner.read_verdicts(GOLD / judge_runner.VERDICTS_FILE)
    if not verdicts:
        typer.echo("no judge verdicts stored yet; run `gate judge run` in CI first", err=True)
        raise typer.Exit(2)
    keys = sorted({v.judge_key for v in verdicts})
    if not judge_key:
        if len(keys) != 1:
            typer.echo(f"--judge-key is one of: {', '.join(keys)}", err=True)
            raise typer.Exit(2)
        judge_key = keys[0]
    mine = [v for v in verdicts if v.judge_key == judge_key]
    if not mine:
        typer.echo(f"no verdicts for {judge_key!r}; stored judges: {', '.join(keys)}", err=True)
        raise typer.Exit(2)

    labels = gold.usable_labels(
        gold.latest_labels(gold.read_labels(GOLD / gold.LABELS_FILE), pass_no=1), g.by_instance
    )
    if not labels:
        typer.echo("no usable human labels yet; `gate gold label` comes first", err=True)
        raise typer.Exit(2)
    lengths = {i.id: len(i.output) for i in g.instances}
    c = calib.calibrate(labels, mine, judge_key=judge_key, lengths=lengths, seed=seed)
    typer.echo(judge_report.render_summary(c))
    if write_doc or out is not None:
        text = judge_report.render(c, gold_instances=len(g.instances), labelled=len(labels))
        target = out if out is not None else DOCS / "judge-calibration.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        typer.echo(f"written to {target}", err=True)


# ---------------------------------------------------------------- the commands that spend


def _panel_or_exit(path: Path) -> Panel:
    try:
        panel = load_panel(path)
    except (OSError, ValueError) as e:
        typer.echo(f"panel {path}: {e}", err=True)
        raise typer.Exit(2) from e
    if not panel.ready:
        unchosen = [a.key for a in panel.arms if "CHOOSE" in a.model]
        typer.echo(
            f"panel {path.name} is not ready: "
            + (f"still to choose: {', '.join(unchosen)}. " if unchosen else "")
            + "Fill the identifier in and set `chosen` to the date you confirmed it against the "
            "vendor's own model list.",
            err=True,
        )
        raise typer.Exit(2)
    return panel


def _refuse_unless_allowed(allowed: bool, what: str) -> None:
    if not allowed:
        typer.echo(
            f"{what} makes vendor calls and would spend money. Pass {VENDOR_FLAG} if this "
            "machine and network are allowed to make them. They are not allowed from the work "
            "network, which inspects TLS; this command is meant for CI.",
            err=True,
        )
        raise typer.Exit(2)


@gold_app.command("generate")
def gold_generate(
    allowed: Annotated[bool, typer.Option(VENDOR_FLAG, help=VENDOR_HELP)] = False,
    panel_path: Annotated[
        Path, typer.Option("--panel", help="the answering models")
    ] = ANSWER_PANEL,
    run_id: Annotated[str, typer.Option(help="names this generation in every instance")] = "",
    limit: Annotated[int, typer.Option(help="stop after this many calls, 0 for no limit")] = 0,
    distractor: Annotated[
        bool,
        typer.Option(
            "--distractors",
            help="the d- stratum: serve each question with a document that cannot answer it",
        ),
    ] = False,
) -> None:
    """Ask three models the gold set's questions. Resumable, and it spends about US$0.40.

    Questions and sources must already be in `gate/gold/`; this writes `instances.jsonl`.
    Nothing is retried: a failed call is stored as an empty answer, which is a real thing a
    judge has to handle and which the labelling rubric has a rule for.
    """
    from boundary import ChatRequest, Gateway

    _refuse_unless_allowed(allowed, "gate gold generate")
    questions = gold.read_questions(GOLD / gold.QUESTIONS_FILE)
    sources = {s.id: s for s in gold.read_sources(GOLD / gold.SOURCES_FILE)}
    if not questions or not sources:
        typer.echo("write the questions and source documents first", err=True)
        raise typer.Exit(2)
    missing = sorted({q.source_id for q in questions} - set(sources))
    if missing:
        typer.echo(f"questions name sources that are not stored: {', '.join(missing)}", err=True)
        raise typer.Exit(2)

    panel = _panel_or_exit(panel_path)
    existing = gold.read_instances(GOLD / gold.INSTANCES_FILE)
    done = {i.id for i in existing}
    if distractor:
        g0 = gold.load(GOLD)
        try:
            jobs = list(distractors.plan(g0, panel.arms))
        except distractors.NoDistractorError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(2) from e
        total = len(jobs)
        typer.echo(
            f"{total} distractor answers planned over "
            f"{len(distractors.questions_for(g0))} questions."
        )
    else:
        jobs = list(generate.plan(questions, sources, panel.arms))
        total = len(jobs)
    typer.echo(f"{total} answers planned, {len(done)} already stored, {total - len(done)} to make.")

    made = 0
    failed = False
    # Appended as each answer comes back, not collected and written at the end. The first real
    # run died on call one of 300 with a vendor 400, and had it died on call 250 instead, every
    # one of those answers would have been paid for and thrown away.
    fresh: list[gold.AnswerInstance] = []
    with Gateway.from_config(
        BOUNDARY_CONFIG,
        project=PROJECT,
        ledger_path=GOLD / "ledger.sqlite",
        raw_store=GOLD / "raw",
    ) as gateway:

        def caller(job: generate.Job) -> object:
            nonlocal made
            if limit and made >= limit:
                raise _LimitReachedError()
            made += 1
            arm: Arm = job.arm
            return gateway.chat(
                ChatRequest(
                    model=arm.explicit,
                    system=generate.ANSWER_SYSTEM,
                    messages=[{"role": "user", "content": job.prompt}],
                    max_tokens=generate.MAX_TOKENS,
                    temperature=None if "temperature" in arm.omit else generate.TEMPERATURE,
                    extra=arm.extra,
                ),
                purpose="gold-set answer",
                run_id=run_id or "gold-1",
            )

        try:
            generate.generate(
                jobs,
                caller,  # type: ignore[arg-type]
                run_id=run_id or "gold-1",
                skip=done,
                on_instance=fresh.append,
            )
        except _LimitReachedError:
            typer.echo(f"stopped at the {limit} calls you asked for")
        # Whatever it was, the answers already paid for are written below before we exit.
        except Exception as e:
            typer.echo(f"generation stopped: {type(e).__name__}: {e}", err=True)
            failed = True

    if fresh:
        gold.write_all(GOLD / gold.INSTANCES_FILE, [*existing, *fresh])
    g = gold.load(GOLD)
    typer.echo(f"{len(g.instances)} instances stored")
    typer.echo(generate.coverage(g))
    for problem in g.problems():
        typer.echo(f"PROBLEM  {problem}", err=True)
    if failed:
        raise typer.Exit(1)


class _LimitReachedError(RuntimeError):
    """The --limit was reached. Raised through the caller because the runner has no notion of
    a budget, and caught immediately; the work already done is kept and committed."""


@judge_app.command("run")
def judge_run(
    allowed: Annotated[bool, typer.Option(VENDOR_FLAG, help=VENDOR_HELP)] = False,
    judge_key: Annotated[str, typer.Option(help="which judge in the judge panel to run")] = "",
    panel_path: Annotated[Path, typer.Option("--panel", help="the judges")] = JUDGE_PANEL,
    repeats: Annotated[int, typer.Option(help="readings per instance; 2 gives test-retest")] = 1,
    swap: Annotated[
        bool, typer.Option(help="also read each case with the parts reordered")
    ] = False,
    limit: Annotated[int, typer.Option(help="stop after this many calls, 0 for no limit")] = 0,
    max_tokens: Annotated[
        int, typer.Option(help="output budget; a thinking model needs room to think first")
    ] = 64,
) -> None:
    """Ask a judge about every gold instance and store what it said. Resumable.

    The verdicts are stored, so `gate judge calibrate` can be re-run as often as you like for
    nothing afterwards.
    """
    from boundary import ChatRequest, Gateway

    _refuse_unless_allowed(allowed, "gate judge run")
    g = _gold_or_exit()
    panel = _panel_or_exit(panel_path)
    arms = {a.key: a for a in panel.arms}
    if not judge_key:
        typer.echo(f"--judge-key is one of: {', '.join(sorted(arms))}", err=True)
        raise typer.Exit(2)
    if judge_key not in arms:
        typer.echo(f"no judge {judge_key!r}; the panel has: {', '.join(sorted(arms))}", err=True)
        raise typer.Exit(2)
    arm = arms[judge_key]
    from gate.judge.rubric import JudgeConfig

    # 64 by default, not 16, for the reason the drift panel raised multiple choice from 16 to
    # 64. It is still not enough for Gemini 3.8 Flash on a 1,000-token judge prompt: on the
    # probe of 2026-09-23, 5 of 6 calls ended at max_tokens having written nothing or "FA".
    # That judge runs with --max-tokens 1024, and every verdict records the budget it had.
    config = JudgeConfig(
        key=judge_key,
        provider=arm.provider,
        model=arm.model,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    path = GOLD / judge_runner.VERDICTS_FILE
    skip = judge_runner.already_done(judge_runner.read_verdicts(path), judge_key)
    planned = len(list(judge_runner.plan(g, repeats=repeats, swap=swap)))
    typer.echo(f"{planned} readings planned, {len(skip)} already stored.")

    made = 0
    with Gateway.from_config(
        BOUNDARY_CONFIG,
        project=PROJECT,
        ledger_path=GOLD / "ledger.sqlite",
        raw_store=GOLD / "raw-judge",
    ) as gateway:

        def caller(*, system: str, prompt: str, config: JudgeConfig) -> object:
            nonlocal made
            if limit and made >= limit:
                raise _LimitReachedError()
            made += 1
            return gateway.chat(
                ChatRequest(
                    model=arm.explicit,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=config.max_tokens,
                    temperature=None if "temperature" in arm.omit else 0.0,
                    extra=arm.extra,
                ),
                purpose="judge calibration",
                run_id=f"judge-{judge_key}",
            )

        try:
            judge_runner.run(
                g,
                config,
                caller,  # type: ignore[arg-type]
                repeats=repeats,
                swap=swap,
                skip=skip,
                on_verdict=lambda v: judge_runner.append_verdict(path, v),
            )
        except _LimitReachedError:
            typer.echo(f"stopped at the {limit} calls you asked for")

    stored = judge_runner.read_verdicts(path)
    mine = [v for v in stored if v.judge_key == judge_key]
    ungradeable = sum(1 for v in mine if not v.gradeable)
    typer.echo(
        f"{len(mine)} verdicts stored for {judge_key}, {ungradeable} not in the two-line form"
    )
    typer.echo(f"verdicts are in {path}")


@gold_app.command("fetch")
def gold_fetch(
    allowed: Annotated[
        bool,
        typer.Option(
            "--i-am-allowed-to-reach-the-internet",
            help="confirm this machine can read public pages; CI passes it",
        ),
    ] = False,
    spec_list: Annotated[Path, typer.Option("--list", help="the pages to fetch")] = SOURCE_LIST,
    only: Annotated[str, typer.Option(help="comma separated ids, for retrying a few")] = "",
) -> None:
    """Read the public regulator pages the gold set's questions are answered from.

    Spends nothing, but it does reach the internet, and an ordinary HTTPS read to canada.ca
    times out from the work network. This runs in the `gold` workflow. Each page is stored as a
    passage with the hash of the bytes it came from and the date it was read, and is never
    fetched again; a page that fails is reported with its reason and the rest are still stored.
    """
    if not allowed:
        typer.echo(
            "gate gold fetch reads public web pages. Pass --i-am-allowed-to-reach-the-internet "
            "if this machine can; it cannot from the work network, whose proxy makes the read "
            "time out. This command is meant for CI.",
            err=True,
        )
        raise typer.Exit(2)
    try:
        specs = gold_sources.load_specs(spec_list)
    except (OSError, ValueError) as e:
        typer.echo(f"source list {spec_list}: {e}", err=True)
        raise typer.Exit(2) from e
    if only:
        wanted = {k.strip() for k in only.split(",") if k.strip()}
        specs = [s for s in specs if s.id in wanted]
        if not specs:
            typer.echo(f"no source in the list matches {only!r}", err=True)
            raise typer.Exit(2)

    path = GOLD / gold.SOURCES_FILE
    existing = gold.read_sources(path)
    have = {s.id for s in existing}
    results = gold_sources.fetch_all(specs, skip=have if not only else set())
    fetched = [r.document for r in results if r.document is not None]
    failed = [r for r in results if not r.ok]

    if fetched:
        by_id = {s.id: s for s in existing}
        for doc in fetched:
            by_id[doc.id] = doc
        gold.write_all(path, [by_id[k] for k in sorted(by_id)])
    for doc in fetched:
        typer.echo(f"  {doc.id}  {len(doc.text):>5} chars  {doc.title}")
    for r in failed:
        typer.echo(f"  {r.spec.id}  FAILED  {r.spec.url}", err=True)
        typer.echo(f"          {r.error}", err=True)
    typer.echo(
        f"{len(fetched)} fetched, {len(failed)} failed, {len(have)} already stored; "
        f"{len(gold.read_sources(path))} documents in all"
    )
    if failed and not fetched:
        raise typer.Exit(1)


@gold_app.command("probe-models")
def gold_probe_models(
    allowed: Annotated[bool, typer.Option(VENDOR_FLAG, help=VENDOR_HELP)] = False,
    models: Annotated[str, typer.Option(help="comma separated provider/model identifiers")] = "",
    max_tokens: Annotated[int, typer.Option(help="tokens to ask for; keep it tiny")] = 8,
) -> None:
    """Ask each named model one trivial question and report whether it answered.

    A vendor's model list is a catalogue, not an inventory of what it will serve you: on
    2026-09-20 two identifiers from the provider's own list of 274 both returned 400 "Unable to
    access non-serverless model". Nothing but a call can tell the difference, so this makes the
    call, once per candidate, for a few tokens, and prints what came back. Cheaper than
    discovering it three hundred calls into a generation run, and quicker than one guess per
    workflow run.
    """
    from boundary import ChatRequest, Gateway

    _refuse_unless_allowed(allowed, "gate gold probe-models")
    wanted = [m.strip() for m in models.split(",") if m.strip()]
    if not wanted:
        typer.echo("--models is a comma separated list of provider/model identifiers", err=True)
        raise typer.Exit(2)
    servable: list[str] = []
    with Gateway.from_config(
        BOUNDARY_CONFIG, project=PROJECT, ledger_path=GOLD / "ledger.sqlite"
    ) as gateway:
        for model in wanted:
            try:
                reply = gateway.chat(
                    ChatRequest(
                        model=model,
                        system="Answer with one word.",
                        messages=[{"role": "user", "content": "Say OK."}],
                        max_tokens=max_tokens,
                        temperature=0.0,
                    ),
                    purpose="probe: is this model servable",
                    run_id="probe",
                )
            except Exception as e:
                # The message is the finding. A 400 naming a dedicated endpoint means the model
                # is catalogued but not served; anything else is its own problem.
                typer.echo(f"  {model}")
                typer.echo(f"      NO  {type(e).__name__}: {e}")
                continue
            text = (reply.text or "").strip().replace(chr(10), " ")[:40]
            costed = "costed" if reply.costed else "UNCOSTED (no price entry)"
            typer.echo(f"  {model}")
            typer.echo(f"      yes  {text!r}  {costed}")
            servable.append(model)
    typer.echo(f"{len(servable)} of {len(wanted)} answered: {', '.join(servable) or 'none'}")
    if not servable:
        raise typer.Exit(1)

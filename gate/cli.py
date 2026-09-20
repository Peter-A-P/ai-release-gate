"""Command line: gate run | compare | aa | power | spec.

Stage 1 (PLAN.md B10): every side comes from Part A's stored records, so no command here
calls a vendor or spends anything. A side is named `MONTH/ARM`, optionally `MONTH/ARM@0,1` to
keep only those repeats.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import Annotated

import typer

from drift.runner.records import arms_recorded, read_records, records_path
from gate import __version__, aa, ledger, report
from gate.decision import decide
from gate.outcomes import NoSuchArmError, Side, part_a_side
from gate.spec import EvalSpec, load_spec
from gate.stats import PowerLine, items_needed

app = typer.Typer(add_completion=False, help=f"gate {__version__}: the release gate")
spec_app = typer.Typer(help="the eval spec")
app.add_typer(spec_app, name="spec")

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "drift" / "runs"
SPECS = ROOT / "gate" / "specs"
DEFAULT_SPEC = SPECS / "drift-blocks.yaml"
LEDGER = ROOT / "gate" / "runs" / ledger.LEDGER_FILE

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

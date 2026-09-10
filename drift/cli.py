"""Command line: drift run | replay | report | items validate | suite freeze | suite verify | panel show.

Paths default to the repository layout in PLAN.md section 5. The runner's boundary
configuration lives in drift/config so the drift record owns its own price snapshot.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from drift import __version__
from drift.analysis.report import (
    build_report,
    metrics_for_month,
    previous_month,
    readme_rows,
    regrade,
    write_readme,
)
from drift.graders import GRADERS, grader
from drift.items import read_items, validate_file
from drift.panel import load_panel
from drift.runner.run import RunConfig, run_month
from drift.suite import freeze, load_suite, verify

app = typer.Typer(add_completion=False, help=f"drift {__version__}: the frozen-suite drift record")
items_app = typer.Typer(help="item files")
suite_app = typer.Typer(help="the frozen suite")
panel_app = typer.Typer(help="the model panel")
app.add_typer(items_app, name="items")
app.add_typer(suite_app, name="suite")
app.add_typer(panel_app, name="panel")

ROOT = Path(__file__).resolve().parent.parent
DRIFT = ROOT / "drift"
SUITE_ROOT = DRIFT / "suite"
RUNS = DRIFT / "runs"
REPORTS = DRIFT / "reports"
PANEL = DRIFT / "panel.yaml"
BOUNDARY_CONFIG = DRIFT / "config" / "boundary.yaml"
PROJECT = "ai-release-gate"


@app.command()
def run(
    month: Annotated[str, typer.Option(help="YYYY-MM the run belongs to")],
    repeats: int = 5,
    items: Annotated[int | None, typer.Option(help="dry run: items per block")] = None,
    arm: Annotated[list[str] | None, typer.Option(help="only these arm keys")] = None,
    expected_cost: float = 9.0,
    abort_multiplier: float = 1.5,
    seed: int = 20260927,
    pause: float = 0.0,
    rerun_of: str | None = None,
    write_readme_table: bool = True,
) -> None:
    """Run the suite against every arm through boundary in pass-through mode, then report."""
    from boundary import Gateway

    suite = load_suite(SUITE_ROOT)
    if not verify(SUITE_ROOT):
        typer.echo(
            "suite files do not match SUITE_HASH; a changed suite is a new version", err=True
        )
        raise typer.Exit(2)
    panel = load_panel(PANEL)
    month_dir = RUNS / month
    month_dir.mkdir(parents=True, exist_ok=True)
    with Gateway.from_config(
        BOUNDARY_CONFIG,
        project=PROJECT,
        ledger_path=month_dir / "ledger.sqlite",
        raw_store=month_dir / "raw",
    ) as gw:
        meta = run_month(
            month=month,
            suite=suite,
            panel=panel,
            gateway=gw,
            runs_root=RUNS,
            config=RunConfig(
                repeats=repeats,
                seed=seed,
                expected_cost_usd=expected_cost,
                abort_multiplier=abort_multiplier,
                items_limit=items,
                arm_keys=tuple(arm) if arm else None,
                pause_s=pause,
                rerun_of=rerun_of,
            ),
        )
    typer.echo(f"run {meta.run_id}: {meta.status}, {meta.calls} calls, US${meta.spent_usd:.2f}")
    out = build_report(RUNS, REPORTS, month, panel)
    typer.echo(f"report: {out}")
    if write_readme_table:
        write_readme(
            ROOT / "README.md",
            readme_rows(
                month,
                metrics_for_month(RUNS, month),
                metrics_for_month(RUNS, previous_month(month)),
            ),
        )
    if meta.status != "complete":
        raise typer.Exit(1)


@app.command()
def replay(month: Annotated[str, typer.Option()]) -> None:
    """Regrade stored outputs with the current graders; no vendor is called."""
    suite = load_suite(SUITE_ROOT)
    for key, (compared, disagreed) in regrade(RUNS, month, suite).items():
        typer.echo(
            f"{key}: {compared} records regraded, {disagreed} disagree with the run-time grade"
        )
    out = build_report(RUNS, REPORTS, month, load_panel(PANEL) if PANEL.is_file() else None)
    typer.echo(f"report: {out}")


@app.command()
def report(month: Annotated[str, typer.Option()], readme: bool = False) -> None:
    """Render the report for a month from the stored records."""
    out = build_report(RUNS, REPORTS, month, load_panel(PANEL) if PANEL.is_file() else None)
    typer.echo(f"report: {out}")
    if readme:
        write_readme(
            ROOT / "README.md",
            readme_rows(
                month,
                metrics_for_month(RUNS, month),
                metrics_for_month(RUNS, previous_month(month)),
            ),
        )


@items_app.command("validate")
def items_validate(path: Path) -> None:
    """Schema, ids, grader names, plain punctuation, prompt length, and the expected value
    against its own grader."""
    problems = validate_file(path, grader_names=GRADERS)
    if not problems:
        for item in read_items(path):
            problems.extend(
                f"{item.id}: {p}" for p in grader(item.grader).check_expected(item.expected)
            )
    for p in problems:
        typer.echo(p, err=True)
    n = sum(1 for _ in read_items(path)) if not problems else 0
    typer.echo(
        f"{path.name}: {'ok, ' + str(n) + ' items' if not problems else str(len(problems)) + ' problem(s)'}"
    )
    raise typer.Exit(1 if problems else 0)


@suite_app.command("freeze")
def suite_freeze(heldout: Path | None = None) -> None:
    """Write SUITE_HASH and, with --heldout FILE, the held-out hashes."""
    h, n = freeze(SUITE_ROOT, heldout_file=heldout)
    typer.echo(f"SUITE_HASH {h}; {n} held-out hashes")


@suite_app.command("verify")
def suite_verify() -> None:
    ok = verify(SUITE_ROOT)
    typer.echo("suite matches SUITE_HASH" if ok else "suite DOES NOT match SUITE_HASH")
    raise typer.Exit(0 if ok else 1)


@panel_app.command("show")
def panel_show() -> None:
    panel = load_panel(PANEL)
    typer.echo(f"panel v{panel.version}, chosen {panel.chosen or 'NOT YET'}; ready: {panel.ready}")
    for a in panel.arms:
        typer.echo(f"  {a.key:<22} {a.arm:<8} {a.family:<10} {a.explicit}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

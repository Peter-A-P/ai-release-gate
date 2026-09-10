"""Command line: drift run | collect | replay | report | sample | items validate | suite freeze
| suite verify | panel show | panel providers | panel candidates.

Paths default to the repository layout in PLAN.md section 5. The runner's boundary
configuration lives in drift/config so the drift record owns its own price snapshot.

The monthly job (drift.yml) runs `drift run --provider X --no-collect` once per provider in
parallel, then `drift collect` once to fold the arm directories into the month's RUN.json, the
report and the README table. A local full run is `drift run` with no selection: the same
thing in one process.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
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
from drift.panel import MODEL_LIST_PATHS, Arm, load_panel, parse_model_list, snapshot_alias_pairs
from drift.runner.records import summarise_month
from drift.runner.run import Callers, RunConfig, run_month
from drift.sampling.sample import (
    DEFAULT_SEED,
    SOURCES,
    Draw,
    differences,
    items_for,
    load_parts,
    today,
    write_draws,
)
from drift.sampling.sample import draw as make_draw
from drift.suite import (
    HeldoutError,
    NotFrozenError,
    Suite,
    freeze,
    load_heldout,
    load_suite,
    verify,
)

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


def _verify_or_exit() -> bool:
    try:
        return verify(SUITE_ROOT)
    except NotFrozenError as e:
        typer.echo(f"suite is not frozen: {e}", err=True)
        raise typer.Exit(2) from e


def _load_suite_or_exit(*, without_heldout: bool) -> Suite:
    suite = load_suite(SUITE_ROOT)
    if not _verify_or_exit():
        typer.echo(
            "suite files do not match SUITE_HASH; a changed suite is a new version", err=True
        )
        raise typer.Exit(2)
    if without_heldout:
        return suite
    try:
        heldout = load_heldout(SUITE_ROOT)
    except HeldoutError as e:
        typer.echo(f"held-out items: {e}", err=True)
        raise typer.Exit(2) from e
    return suite.with_heldout(heldout)


@contextmanager
def _open_callers(arm: Arm, arm_dir: Path) -> Iterator[Callers]:
    """Two real gateways on one ledger: the held-out one writes its raw store to a directory
    that is never committed."""
    from boundary import Gateway

    arm_dir.mkdir(parents=True, exist_ok=True)
    ledger = arm_dir / "ledger.sqlite"
    with (
        Gateway.from_config(
            BOUNDARY_CONFIG, project=PROJECT, ledger_path=ledger, raw_store=arm_dir / "raw"
        ) as public,
        Gateway.from_config(
            BOUNDARY_CONFIG, project=PROJECT, ledger_path=ledger, raw_store=arm_dir / "raw-heldout"
        ) as heldout,
    ):
        yield Callers(public=public, heldout=heldout)


def _collect(month: str, *, write_readme_table: bool) -> bool:
    panel = load_panel(PANEL)
    meta = summarise_month(RUNS, month, [a.key for a in panel.arms])
    if meta is None:
        typer.echo(f"no arm has recorded anything for {month}", err=True)
        return False
    typer.echo(
        f"run {meta.run_id}: {meta.status}"
        + (f" ({meta.reason})" if meta.reason else "")
        + f", {len(meta.arms)} arms, {meta.calls} calls, US${meta.spent_usd:.2f}"
    )
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
    return meta.status == "complete"


@app.command()
def run(
    month: Annotated[str, typer.Option(help="YYYY-MM the run belongs to")],
    repeats: int = 5,
    items: Annotated[int | None, typer.Option(help="dry run: items per block")] = None,
    arm: Annotated[list[str] | None, typer.Option(help="only these arm keys")] = None,
    provider: Annotated[list[str] | None, typer.Option(help="only these providers' arms")] = None,
    expected_cost: Annotated[
        float | None,
        typer.Option(help="expected US$ for the arms run here; default: from the price list"),
    ] = None,
    abort_multiplier: float = 1.5,
    seed: int = 20260927,
    pause: float = 0.0,
    rerun_of: str | None = None,
    without_heldout: Annotated[
        bool, typer.Option("--without-heldout", help="public items only (dry runs)")
    ] = False,
    collect: Annotated[
        bool, typer.Option(help="fold the arms into RUN.json, the report and the README after")
    ] = True,
) -> None:
    """Run the suite against the selected arms through boundary in pass-through mode."""
    from boundary.config import latest_price_list, load_config

    suite = _load_suite_or_exit(without_heldout=without_heldout)
    panel = load_panel(PANEL)
    prices = latest_price_list(load_config(BOUNDARY_CONFIG).prices)
    metas = run_month(
        month=month,
        suite=suite,
        panel=panel,
        open_callers=_open_callers,
        runs_root=RUNS,
        config=RunConfig(
            repeats=repeats,
            seed=seed,
            expected_cost_usd=expected_cost,
            abort_multiplier=abort_multiplier,
            items_limit=items,
            arm_keys=tuple(arm) if arm else None,
            providers=tuple(provider) if provider else None,
            pause_s=pause,
            rerun_of=rerun_of,
        ),
        prices=prices,
    )
    for m in metas:
        typer.echo(
            f"{m.arms[0]}: {m.status}"
            + (f" ({m.reason})" if m.reason else "")
            + f", {m.calls} calls, US${m.spent_usd:.2f} of an expected US${m.expected_cost_usd:.2f}"
        )
    ok = all(m.status == "complete" for m in metas)
    if collect:
        ok = _collect(month, write_readme_table=True) and ok
    if not ok:
        raise typer.Exit(1)


@app.command()
def collect(
    month: Annotated[str, typer.Option()],
    readme: bool = True,
) -> None:
    """Fold the arm directories of a month into RUN.json, the report and the README table.
    Exit 1 when any arm is missing or not complete; the records are kept either way."""
    if not _collect(month, write_readme_table=readme):
        raise typer.Exit(1)


@app.command()
def replay(month: Annotated[str, typer.Option()]) -> None:
    """Regrade stored outputs with the current graders; no vendor is called. Held-out
    records store no output and are skipped."""
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


@app.command()
def sample(
    seed: int = DEFAULT_SEED,
    check: Annotated[
        bool,
        typer.Option("--check", help="compare a fresh draw with the files on disk, write nothing"),
    ] = False,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="re-fetch the sources instead of using the cache")
    ] = False,
    cache: Path = ROOT / ".cache" / "sources",
) -> None:
    """Draw the public half of suite v1 from the public sources, once (PLAN.md section 3).

    Writes drift/suite/v1/<block>-<source>.jsonl and SOURCES.json, and refuses to run against
    a frozen suite. --check re-draws into memory and reports any difference from the files,
    which is how the published items are audited after the freeze.

    Every source is drawn on every invocation, and there is deliberately no way to draw one:
    ids are assigned per block across all of them and the manifest describes the whole draw,
    so a partial run would renumber items and drop the rest from the record. From the cache it
    takes a few seconds.
    """
    specs = list(SOURCES)
    sampled_on = today()
    draws: list[Draw] = []
    for spec in specs:
        parts, provenance = load_parts(spec, cache, refresh=refresh)
        d = make_draw(spec, parts, provenance, seed=seed)
        draws.append(d)
        typer.echo(
            f"{spec.name}: {len(parts)} rows, {len(d.built.candidates)} eligible, "
            f"{len(d.chosen)} sampled into {spec.block}"
            + (f", rejected {d.built.rejected}" if d.built.rejected else "")
        )
    items = items_for(draws, seed=seed, sampled_on=sampled_on)
    if check:
        problems = differences(SUITE_ROOT, items)
        for p in problems:
            typer.echo(p, err=True)
        typer.echo(
            "the files on disk are the draw for this seed"
            if not problems
            else f"{len(problems)} source file(s) differ from the draw"
        )
        raise typer.Exit(1 if problems else 0)
    path = write_draws(SUITE_ROOT, draws, items, seed=seed, sampled_on=sampled_on)
    typer.echo(f"{sum(len(v) for v in items.values())} items written; manifest {path.name}")


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
def suite_verify(
    heldout: Annotated[
        bool, typer.Option(help="also check the held-out items from the environment")
    ] = False,
) -> None:
    ok = _verify_or_exit()
    typer.echo("suite matches SUITE_HASH" if ok else "suite DOES NOT match SUITE_HASH")
    if heldout:
        try:
            items = load_heldout(SUITE_ROOT)
            typer.echo(f"{len(items)} held-out items match the committed hashes")
        except HeldoutError as e:
            typer.echo(f"held-out items: {e}", err=True)
            ok = False
    raise typer.Exit(0 if ok else 1)


@panel_app.command("show")
def panel_show() -> None:
    panel = load_panel(PANEL)
    typer.echo(f"panel v{panel.version}, chosen {panel.chosen or 'NOT YET'}; ready: {panel.ready}")
    for a in panel.arms:
        typer.echo(f"  {a.key:<26} {a.arm:<8} {a.family:<14} {a.explicit}")


@panel_app.command("providers")
def panel_providers(
    as_json: Annotated[
        bool, typer.Option("--json", help="a JSON list, for the job matrix")
    ] = False,
) -> None:
    """The providers in the panel, one parallel job each in the monthly workflow."""
    providers = load_panel(PANEL).providers
    typer.echo(json.dumps(providers) if as_json else "\n".join(providers))


@panel_app.command("candidates")
def panel_candidates(
    provider: Annotated[list[str] | None, typer.Option(help="only these providers")] = None,
    contains: Annotated[str | None, typer.Option(help="only ids containing this")] = None,
) -> None:
    """List the identifiers each vendor currently offers, and the snapshot and alias pairs
    among them, so the panel can be chosen from the vendors' own lists.

    These are real vendor calls (free: no tokens), made through boundary's escape hatch so
    they are ledgered. Run them from a network that does not inspect TLS.
    """
    from boundary import Gateway

    names = provider or list(MODEL_LIST_PATHS)
    with Gateway.from_config(BOUNDARY_CONFIG, project=PROJECT) as gw:
        for name in names:
            path = MODEL_LIST_PATHS.get(name)
            if path is None:
                typer.echo(f"{name}: no model-list endpoint known", err=True)
                continue
            resp = gw.raw(name, "GET", path, None, purpose="panel-candidates")
            if resp.status != 200:
                detail = resp.body[:200].decode("utf-8", "replace")
                typer.echo(f"{name}: {resp.status} {detail}", err=True)
                continue
            ids = [i for i in parse_model_list(name, resp.json) if not contains or contains in i]
            pairs = snapshot_alias_pairs(ids)
            typer.echo("")
            typer.echo(f"{name}: {len(ids)} identifiers")
            for i in ids:
                typer.echo(f"  {i}")
            if pairs:
                typer.echo(f"  snapshot and alias pairs ({len(pairs)}):")
                for snap, alias in pairs:
                    typer.echo(f"    snapshot {snap}  <->  alias {alias}")
            else:
                typer.echo("  no dated snapshot with a matching undated alias")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

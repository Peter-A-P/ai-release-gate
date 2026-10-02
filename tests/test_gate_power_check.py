"""The power function checked against real answers (gate/power_check.py)."""

from __future__ import annotations

from pathlib import Path

from drift.runner.records import arms_recorded, read_records, records_path
from gate import power_check
from gate.spec import load_spec

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "drift" / "runs"


def test_the_check_is_seeded_and_its_figures_are_the_committed_reports() -> None:
    spec = load_spec(ROOT / "gate" / "specs" / "drift-blocks.yaml")
    arm = "openai-snapshot"
    assert arm in arms_recorded(RUNS, "2026-10")
    recs = {arm: list(read_records(records_path(RUNS, "2026-10", arm)))}
    one = power_check.check(spec, recs, month="2026-10", sizes=(40, 120), deltas=(3.0,), draws=20)
    two = power_check.check(spec, recs, month="2026-10", sizes=(40, 120), deltas=(3.0,), draws=20)
    assert one == two
    small, large = one.cell(arm, 3.0, 40), one.cell(arm, 3.0, 120)
    assert small.rate.point < large.rate.point, "more items, more power"
    assert one.predicted[3.0] == (118, 222)
    committed = (ROOT / "gate" / "reports" / "power-check-2026-10.md").read_text(encoding="utf-8")
    assert "The bank asks for **118** items" in committed
    assert "| google-alias |" in committed


def test_the_smallest_powered_size_must_hold_at_every_larger_size() -> None:
    from drift.analysis.stats import Estimate

    def cell(n: int, rate: float) -> power_check.Cell:
        return power_check.Cell(
            "a", 3.0, n, round(rate * 100), 100, Estimate(rate, rate, rate, 100)
        )

    pc = power_check.PowerCheck(
        "m", "s", "h", (cell(80, 0.2), cell(120, 0.82), cell(160, 0.77), cell(240, 0.99)), {}
    )
    assert pc.smallest_powered("a", 3.0) == 240

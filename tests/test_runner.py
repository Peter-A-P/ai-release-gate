"""The runner against a fake gateway: pass-through only, every call recorded, resume, cap
abort, and the analysis from the records."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from boundary import ChatRequest, ChatResponse, Mode, Usage

from drift.analysis.metrics import arm_metrics, drift_declared, month_over_month
from drift.analysis.report import (
    build_report,
    metrics_for_month,
    readme_rows,
    regrade,
    write_readme,
)
from drift.panel import Panel
from drift.runner.records import load_meta, read_records, records_path
from drift.runner.run import RunConfig, plan_calls, run_month
from drift.suite import Suite


class FakeLedger:
    def __init__(self) -> None:
        self.spent: dict[str | None, float] = {}

    def spend_usd(
        self, *, project: str | None, year_month: str | None = None, run_id: str | None = None
    ) -> float:
        return self.spent.get(run_id, 0.0)


class FakeGateway:
    """Answers reasoning items correctly with probability p, records every request it sees."""

    project = "ai-release-gate"

    def __init__(self, p_correct: float = 1.0, seed: int = 0, cost_per_call: float = 0.001) -> None:
        self.ledger = FakeLedger()
        self.requests: list[tuple[ChatRequest, str, Mode]] = []
        self.rng = random.Random(seed)
        self.p = p_correct
        self.cost = cost_per_call
        self.n = 0

    def chat(
        self,
        request: ChatRequest,
        *,
        purpose: str,
        run_id: str | None = None,
        mode: Mode = Mode.STANDARD,
    ) -> ChatResponse:
        self.requests.append((request, purpose, mode))
        self.n += 1
        self.ledger.spent[run_id] = self.ledger.spent.get(run_id, 0.0) + self.cost
        prompt = str(request.messages[0]["content"])
        if "plus" in prompt:
            a = int(prompt.split()[2])
            text = f"#### {2 * a if self.rng.random() < self.p else 2 * a + 1}"
        elif "letter comes first" in prompt:
            text = "A"
        elif "acetaminophen" in prompt:
            text = "The labelled maximum is 4 g per day."
        else:
            text = "I can't help with that request."
        return ChatResponse(
            text=text,
            finish_reason="end_turn",
            usage=Usage(input_tokens=30, output_tokens=5),
            cost_usd=self.cost,
            costed=True,
            model_requested=request.model,
            model_returned=request.model.split("/", 1)[1],
            provider=request.model.split("/", 1)[0],
            latency_ms=12.0,
            status=200,
            headers={"request-id": f"req_{self.n}"},
            raw=None,
            ledger_id=self.n,
            mode=mode,
        )


def test_plan_is_shuffled_deterministically() -> None:
    from .conftest import make_items

    items = make_items()
    a = plan_calls(items, 3, 1, "x")
    assert a == plan_calls(items, 3, 1, "x")
    assert a != plan_calls(items, 3, 1, "y")
    assert len(a) == len(items) * 3 and len(set(a)) == len(a)


def test_run_records_every_call_in_passthrough_and_resumes(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    gw = FakeGateway()
    runs = tmp_path / "runs"
    cfg = RunConfig(repeats=2, seed=1, pause_s=0.0)
    meta = run_month(
        month="2026-09",
        suite=suite,
        panel=panel,
        gateway=gw,
        runs_root=runs,
        config=cfg,
        log=lambda _s: None,
    )
    assert meta.status == "complete"
    assert meta.calls == len(suite.items) * 2 * len(panel.arms)
    assert all(m is Mode.PASSTHROUGH and p == "drift-run" for _, p, m in gw.requests)
    assert all(r.max_tokens is not None and r.temperature == 0.0 for r, _, _ in gw.requests)
    recs = list(read_records(records_path(runs, "2026-09", "a-snapshot")))
    assert len(recs) == len(suite.items) * 2
    assert all(r.correct is not None and r.request_id for r in recs)
    # Resume: nothing left to do, no new calls.
    before = gw.n
    run_month(
        month="2026-09",
        suite=suite,
        panel=panel,
        gateway=gw,
        runs_root=runs,
        config=cfg,
        log=lambda _s: None,
    )
    assert gw.n == before


def test_cap_abort_marks_partial_and_keeps_records(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    gw = FakeGateway(cost_per_call=1.0)
    cfg = RunConfig(repeats=1, expected_cost_usd=2.0, abort_multiplier=1.5)
    meta = run_month(
        month="2026-09",
        suite=suite,
        panel=panel,
        gateway=gw,
        runs_root=tmp_path,
        config=cfg,
        log=lambda _s: None,
    )
    assert meta.status == "partial" and meta.reason and "passed 1.5x" in meta.reason
    assert 3 <= meta.calls <= 4
    assert load_meta(tmp_path, "2026-09") is not None


def test_refuses_an_unchosen_panel(suite: Suite, tmp_path: Path) -> None:
    from drift.panel import load_panel

    panel = load_panel(Path(__file__).resolve().parent.parent / "drift" / "panel.yaml")
    with pytest.raises(ValueError, match="choose"):
        run_month(
            month="2026-09",
            suite=suite,
            panel=panel,
            gateway=FakeGateway(),
            runs_root=tmp_path,
            config=RunConfig(),
        )


def test_metrics_month_over_month_and_drift_call(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    runs = tmp_path / "runs"
    cfg = RunConfig(repeats=3, seed=1)
    run_month(
        month="2026-09",
        suite=suite,
        panel=panel,
        gateway=FakeGateway(p_correct=1.0),
        runs_root=runs,
        config=cfg,
        log=lambda _s: None,
    )
    run_month(
        month="2026-10",
        suite=suite,
        panel=panel,
        gateway=FakeGateway(p_correct=0.2, seed=3),
        runs_root=runs,
        config=cfg,
        log=lambda _s: None,
    )
    sep = metrics_for_month(runs, "2026-09")
    octo = metrics_for_month(runs, "2026-10")
    assert sep["a-snapshot"].accuracy.point == 1.0
    assert sep["a-snapshot"].same_day_flip_rate.point == 0.0
    assert octo["a-snapshot"].accuracy.point < 1.0
    mom = month_over_month(sep["a-snapshot"], octo["a-snapshot"])
    assert mom.paired_items == len(suite.items) and mom.correct_to_incorrect > 0
    control = month_over_month(sep["control"], octo["control"])
    # The fake control arm changes the same way, so no drift is declared against it.
    assert not drift_declared(mom, octo["a-snapshot"], control)
    # Against a stable control, the change is above both the noise floor and the control.
    stable_control = month_over_month(sep["control"], sep["control"])
    assert drift_declared(mom, octo["a-snapshot"], stable_control) == (
        mom.flip_rate.point > octo["a-snapshot"].same_day_flip_rate.hi
    )
    m = arm_metrics("x", list(read_records(records_path(runs, "2026-10", "a-snapshot"))))
    assert m.refusal_rate_should_refuse.point == 1.0 and m.refusal_rate_should_answer.point == 0.0
    assert m.cost_per_1000_calls_usd == pytest.approx(1.0)


def test_report_replay_and_readme(suite: Suite, panel: Panel, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_month(
        month="2026-09",
        suite=suite,
        panel=panel,
        gateway=FakeGateway(),
        runs_root=runs,
        config=RunConfig(repeats=2),
        log=lambda _s: None,
    )
    out = build_report(runs, tmp_path / "reports", "2026-09", panel)
    text = out.read_text(encoding="utf-8")
    assert (
        "# Drift record, 2026-09" in text
        and "a-snapshot" in text
        and "first paired comparison" in text
    )
    assert regrade(runs, "2026-09", suite) == {
        k: (len(suite.items) * 2, 0) for k in ("a-alias", "a-snapshot", "control")
    }
    readme = tmp_path / "README.md"
    readme.write_text("x\n<!-- drift:start -->\n| old |\n<!-- drift:end -->\ny\n", encoding="utf-8")
    write_readme(readme, readme_rows("2026-09", metrics_for_month(runs, "2026-09"), {}))
    t = readme.read_text(encoding="utf-8")
    assert "| old |" not in t and "| 2026-09 | a-snapshot |" in t and "first month" in t

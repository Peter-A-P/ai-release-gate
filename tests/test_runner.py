"""The runner against a fake gateway: pass-through only, every call recorded, resume, cap
abort, per-arm directories folded into the month, held-out redaction, and the analysis from
the records."""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from boundary import ChatRequest, ChatResponse, Mode, Usage
from boundary.config import PriceEntry, PriceList

from drift.analysis.metrics import arm_metrics, drift_declared, month_over_month
from drift.analysis.report import (
    build_report,
    metrics_for_month,
    readme_rows,
    regrade,
    write_readme,
)
from drift.items import Item
from drift.panel import Arm, Panel
from drift.runner.records import (
    arm_dir,
    arms_recorded,
    load_meta,
    read_records,
    records_path,
    summarise_month,
)
from drift.runner.run import (
    Callers,
    RunConfig,
    estimate_arm_cost_usd,
    plan_calls,
    run_month,
)
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
        elif "return JSON" in prompt:
            text = '{"a": 1}'
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


def factory(gw: FakeGateway, heldout: FakeGateway | None = None):  # type: ignore[no-untyped-def]
    """A caller factory that hands every arm the same fake gateway(s)."""

    @contextmanager
    def open_callers(arm: Arm, arm_dir: Path) -> Iterator[Callers]:
        yield Callers(public=gw, heldout=heldout or gw)

    return open_callers


def run(suite: Suite, panel: Panel, gw: FakeGateway, runs: Path, cfg: RunConfig, **kw: object):  # type: ignore[no-untyped-def]
    return run_month(
        month=str(kw.pop("month", "2026-09")),
        suite=suite,
        panel=panel,
        open_callers=factory(gw, kw.pop("heldout", None)),  # type: ignore[arg-type]
        runs_root=runs,
        config=cfg,
        log=lambda _s: None,
        **kw,  # type: ignore[arg-type]
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
    cfg = RunConfig(repeats=2, seed=1, pause_s=0.0, expected_cost_usd=3.0)
    metas = run(suite, panel, gw, runs, cfg)
    assert [m.status for m in metas] == ["complete"] * len(panel.arms)
    assert sum(m.calls for m in metas) == len(suite.items) * 2 * len(panel.arms)
    # An explicit expected cost is split evenly when there is no price list to split by.
    assert all(m.expected_cost_usd == pytest.approx(1.0) for m in metas)
    assert all(m is Mode.PASSTHROUGH and p == "drift-run" for _, p, m in gw.requests)
    assert all(r.max_tokens is not None and r.temperature == 0.0 for r, _, _ in gw.requests)
    recs = list(read_records(records_path(runs, "2026-09", "anthropic-snapshot")))
    assert len(recs) == len(suite.items) * 2
    assert all(r.correct is not None and r.request_id for r in recs)
    # One directory per arm, with the arm's own RUN.json.
    assert arms_recorded(runs, "2026-09") == sorted(a.key for a in panel.arms)
    assert (arm_dir(runs, "2026-09", "openweights-control") / "RUN.json").is_file()
    assert load_meta(runs, "2026-09", "anthropic-alias") is not None
    # Resume: nothing left to do, no new calls.
    before = gw.n
    run(suite, panel, gw, runs, cfg)
    assert gw.n == before


def test_provider_selection_and_month_summary(suite: Suite, panel: Panel, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    cfg = RunConfig(repeats=1, expected_cost_usd=1.0, providers=("anthropic",))
    metas = run(suite, panel, FakeGateway(), runs, cfg)
    assert sorted(m.arms[0] for m in metas) == ["anthropic-alias", "anthropic-snapshot"]
    expected = [a.key for a in panel.arms]
    # One provider done: the month is partial and names the arm not yet run.
    summary = summarise_month(runs, "2026-09", expected)
    assert summary is not None and summary.status == "partial"
    assert summary.reason and "openweights-control: not run" in summary.reason
    assert summary.calls == len(suite.items) * 2
    # The other provider arrives (as it would from another job's artifact): complete.
    run(
        suite,
        panel,
        FakeGateway(),
        runs,
        RunConfig(repeats=1, expected_cost_usd=1.0, providers=("openweights",)),
    )
    summary = summarise_month(runs, "2026-09", expected)
    assert summary is not None and summary.status == "complete" and summary.reason is None
    assert summary.arms == sorted(expected) and summary.calls == len(suite.items) * 3
    assert load_meta(runs, "2026-09") is not None  # the month's RUN.json is on disk
    assert summarise_month(runs, "2026-10", expected) is None
    with pytest.raises(ValueError, match="no arm matches"):
        run(
            suite,
            panel,
            FakeGateway(),
            runs,
            RunConfig(expected_cost_usd=1.0, providers=("nobody",)),
        )


def test_cap_abort_marks_partial_and_keeps_records(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    gw = FakeGateway(cost_per_call=1.0)
    cfg = RunConfig(
        repeats=1, expected_cost_usd=6.0, abort_multiplier=1.5, arm_keys=("anthropic-snapshot",)
    )
    (meta,) = run(suite, panel, gw, tmp_path, cfg)
    # The single arm gets the whole explicit budget: 6.0 x 1.5 = 9, so the tenth call aborts.
    assert meta.status == "partial" and meta.reason and "passed 1.5x" in meta.reason
    assert 9 <= meta.calls <= 10
    assert load_meta(tmp_path, "2026-09", "anthropic-snapshot") is not None


def test_expected_cost_from_the_price_list(suite: Suite, panel: Panel, tmp_path: Path) -> None:
    prices = PriceList(
        version=1,
        date=dt.date(2026, 9, 9),
        currency="USD",
        source="test",
        per_million_tokens={
            "anthropic": {
                "claude-test-20260101": PriceEntry(input=1.0, output=5.0),
                "claude-test": PriceEntry(input=1.0, output=5.0),
            },
            "openweights": {"org/open-70b": PriceEntry(input=0.5, output=0.5)},
        },
    )
    calls = len(suite.items) * 2
    est = estimate_arm_cost_usd(panel.arms[0], calls, prices)
    assert est == pytest.approx(calls * (700 * 1.0 + 150 * 5.0) / 1e6)
    assert estimate_arm_cost_usd(panel.arms[0], calls, None) is None
    metas = run(suite, panel, FakeGateway(), tmp_path, RunConfig(repeats=2), prices=prices)
    by_key = {m.arms[0]: m for m in metas}
    assert by_key["anthropic-snapshot"].expected_cost_usd == pytest.approx(est)
    assert by_key["openweights-control"].expected_cost_usd == pytest.approx(
        calls * (700 * 0.5 + 150 * 0.5) / 1e6
    )
    # An explicit total is split in proportion to the estimates.
    metas = run(
        suite,
        panel,
        FakeGateway(),
        tmp_path / "b",
        RunConfig(repeats=2, expected_cost_usd=10.0),
        prices=prices,
    )
    assert sum(m.expected_cost_usd for m in metas) == pytest.approx(10.0)
    assert max(m.expected_cost_usd for m in metas) > min(m.expected_cost_usd for m in metas)
    # A model the price list does not know needs an explicit expected cost.
    unpriced = PriceList(
        version=1, date=dt.date(2026, 9, 9), currency="USD", source="t", per_million_tokens={}
    )
    with pytest.raises(ValueError, match="no price for"):
        run(suite, panel, FakeGateway(), tmp_path / "c", RunConfig(), prices=unpriced)


def test_arm_extra_fields_are_sent_with_every_call(suite: Suite, tmp_path: Path) -> None:
    """A vendor field fixed on the arm (reasoning_effort for an OpenAI reasoning model) goes
    out verbatim on each request of that arm and on no other arm's."""
    panel = Panel(
        version=1,
        chosen=dt.date(2026, 9, 27),
        arms=[
            Arm(
                key="openai-snapshot",
                provider="openai",
                model="gpt-x-2026-01-01",
                arm="snapshot",
                family="gpt",
                extra={"reasoning_effort": "minimal"},
            ),
            Arm(key="openai-alias", provider="openai", model="gpt-x", arm="alias", family="gpt"),
        ],
    )
    gw = FakeGateway()
    run(suite, panel, gw, tmp_path, RunConfig(repeats=1, expected_cost_usd=1.0))
    by_model = {r.model: r.extra for r, _, _ in gw.requests}
    assert dict(by_model["openai/gpt-x-2026-01-01"]) == {"reasoning_effort": "minimal"}
    assert dict(by_model["openai/gpt-x"]) == {}


def test_refuses_an_unchosen_panel(suite: Suite, tmp_path: Path) -> None:
    """Built here rather than loaded from the repository: the repository's panel was chosen on
    2026-09-12, and a test of the refusal must not depend on it being unchosen."""
    from drift.panel import Arm, Panel

    unchosen = Panel(
        version=1,
        chosen=None,
        arms=[
            Arm(
                key="openweights-control",
                provider="openweights",
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                arm="control",
                family="control",
            )
        ],
    )
    with pytest.raises(ValueError, match="choose"):
        run(suite, unchosen, FakeGateway(), tmp_path, RunConfig(expected_cost_usd=1.0))


def test_refuses_a_panel_with_an_identifier_still_to_choose(suite: Suite, tmp_path: Path) -> None:
    """Dated but still carrying a placeholder: `ready` requires both, so a half-filled panel
    cannot be run by setting the date."""
    from drift.panel import Arm, Panel

    half_filled = Panel(
        version=1,
        chosen=dt.date(2026, 9, 12),
        arms=[
            Arm(
                key="openweights-control",
                provider="openweights",
                model="CHOOSE-open-weights-model-with-fixed-weights",
                arm="control",
                family="control",
            )
        ],
    )
    with pytest.raises(ValueError, match="choose"):
        run(suite, half_filled, FakeGateway(), tmp_path, RunConfig(expected_cost_usd=1.0))


def _heldout_items() -> list[Item]:
    return [
        Item(
            id=f"extract-{i:04d}",
            block="structured_extraction",
            system="Answer only with the JSON object requested. No prose.",
            prompt=f"Read the passage and return JSON with key a. Passage: the value is one. ({i})",
            grader="json_schema_exact",
            expected={"schema": {"type": "object"}, "values": {"a": 1}},
            held_out=True,
            source="test",
            licence="CC0",
        )
        for i in range(2)
    ]


def test_heldout_items_are_run_apart_and_recorded_without_output(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    full = suite.with_heldout(_heldout_items())
    assert full.hash == suite.hash and full.heldout_count == 2
    public_gw, heldout_gw = FakeGateway(), FakeGateway()
    runs = tmp_path / "runs"
    cfg = RunConfig(repeats=2, expected_cost_usd=3.0, arm_keys=("anthropic-snapshot",))
    (meta,) = run(full, panel, public_gw, runs, cfg, heldout=heldout_gw)
    assert meta.status == "complete" and meta.heldout_items == 2
    # Held-out calls went through the held-out gateway only.
    assert heldout_gw.n == 2 * 2 and public_gw.n == len(suite.items) * 2
    recs = list(read_records(records_path(runs, "2026-09", "anthropic-snapshot")))
    held = [r for r in recs if r.held_out]
    assert len(held) == 4
    assert all(
        r.output is None and r.normalised is None and r.detail is None and r.output_sha256
        for r in held
    )
    assert all(r.correct is True for r in held)
    assert all(r.output is not None and r.output_sha256 is None for r in recs if not r.held_out)
    # Nothing in the committed record contains the held-out prompt or its answer.
    text = records_path(runs, "2026-09", "anthropic-snapshot").read_text(encoding="utf-8")
    assert "the value is one" not in text and '{"a": 1}' not in text
    # Reported apart from the public block, and the report carries the check.
    m = metrics_for_month(runs, "2026-09")["anthropic-snapshot"]
    assert "structured_extraction (held out)" in m.accuracy_by_block
    assert m.accuracy_by_block["structured_extraction (held out)"].point == 1.0
    # Replay skips them (no output to regrade) without failing.
    compared, disagreed = regrade(runs, "2026-09", full)["anthropic-snapshot"]
    assert compared == len(suite.items) * 2 and disagreed == 0
    with pytest.raises(ValueError, match="already in the public suite"):
        full.with_heldout(_heldout_items())


def test_metrics_month_over_month_and_drift_call(
    suite: Suite, panel: Panel, tmp_path: Path
) -> None:
    runs = tmp_path / "runs"
    cfg = RunConfig(repeats=3, seed=1, expected_cost_usd=3.0)
    run(suite, panel, FakeGateway(p_correct=1.0), runs, cfg)
    run(suite, panel, FakeGateway(p_correct=0.2, seed=3), runs, cfg, month="2026-10")
    sep = metrics_for_month(runs, "2026-09")
    octo = metrics_for_month(runs, "2026-10")
    assert sep["anthropic-snapshot"].accuracy.point == 1.0
    assert sep["anthropic-snapshot"].same_day_flip_rate.point == 0.0
    assert octo["anthropic-snapshot"].accuracy.point < 1.0
    mom = month_over_month(sep["anthropic-snapshot"], octo["anthropic-snapshot"])
    assert mom.paired_items == len(suite.items) and mom.correct_to_incorrect > 0
    control = month_over_month(sep["openweights-control"], octo["openweights-control"])
    # The fake control arm changes the same way, so no drift is declared against it.
    assert not drift_declared(mom, octo["anthropic-snapshot"], control)
    # Against a stable control, the change is above both the noise floor and the control.
    stable_control = month_over_month(sep["openweights-control"], sep["openweights-control"])
    assert drift_declared(mom, octo["anthropic-snapshot"], stable_control) == (
        mom.flip_rate.point > octo["anthropic-snapshot"].same_day_flip_rate.hi
    )
    m = arm_metrics("x", list(read_records(records_path(runs, "2026-10", "anthropic-snapshot"))))
    assert m.refusal_rate_should_refuse.point == 1.0 and m.refusal_rate_should_answer.point == 0.0
    assert m.cost_per_1000_calls_usd == pytest.approx(1.0)


def test_report_replay_and_readme(suite: Suite, panel: Panel, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    full = suite.with_heldout(_heldout_items())
    run(full, panel, FakeGateway(), runs, RunConfig(repeats=2, expected_cost_usd=3.0))
    summarise_month(runs, "2026-09", [a.key for a in panel.arms])
    out = build_report(runs, tmp_path / "reports", "2026-09", panel)
    text = out.read_text(encoding="utf-8")
    assert "# Drift record, 2026-09" in text and "anthropic-snapshot" in text
    assert "first paired comparison" in text and "(2 held out)" in text
    assert "## Held-out check" in text and "| anthropic-snapshot | structured_extraction |" in text
    assert regrade(runs, "2026-09", full) == {
        k: (len(suite.items) * 2, 0)
        for k in ("anthropic-alias", "anthropic-snapshot", "openweights-control")
    }
    readme = tmp_path / "README.md"
    readme.write_text("x\n<!-- drift:start -->\n| old |\n<!-- drift:end -->\ny\n", encoding="utf-8")
    write_readme(readme, readme_rows("2026-09", metrics_for_month(runs, "2026-09"), {}))
    t = readme.read_text(encoding="utf-8")
    assert "| old |" not in t and "| 2026-09 | anthropic-snapshot |" in t and "first month" in t

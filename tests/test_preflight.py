"""The pre-run probe: a dead control stops the run, a dead vendor arm does not."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from boundary import ChatRequest, ChatResponse, Mode, Usage

from drift.panel import Arm, Panel
from drift.runner.preflight import PROBE_MAX_TOKENS, ProbeFactory, preflight
from drift.runner.run import Caller

NOT_SERVERLESS = {
    "error": {
        "message": "Unable to access non-serverless model meta-llama/Llama-3.3-70B-Instruct-Turbo.",
        "type": "invalid_request_error",
        "code": "model_not_available",
    }
}


class Ledger:
    def spend_usd(
        self, *, project: str | None, year_month: str | None = None, run_id: str | None = None
    ) -> float:
        return 0.0


class Vendor:
    """Answers OK, except for the arm keys it is told are gone, which get Together's 400."""

    project = "ai-release-gate"

    def __init__(self, dead: set[str]) -> None:
        self.ledger = Ledger()
        self.dead = dead
        self.seen: list[tuple[ChatRequest, str, Mode]] = []

    def caller(self, arm: Arm) -> Caller:
        vendor = self

        class One:
            project = vendor.project
            ledger = vendor.ledger

            def chat(
                self,
                request: ChatRequest,
                *,
                purpose: str,
                run_id: str | None = None,
                mode: Mode = Mode.STANDARD,
            ) -> ChatResponse:
                vendor.seen.append((request, purpose, mode))
                dead = arm.key in vendor.dead
                return ChatResponse(
                    text=None if dead else "OK",
                    finish_reason=None if dead else "stop",
                    usage=Usage(input_tokens=0 if dead else 8, output_tokens=0 if dead else 1),
                    cost_usd=None if dead else 0.00001,
                    costed=not dead,
                    model_requested=request.model,
                    model_returned=None if dead else request.model,
                    provider=arm.provider,
                    latency_ms=10.0,
                    status=400 if dead else 200,
                    headers={},
                    raw=NOT_SERVERLESS if dead else {},
                    ledger_id=1,
                    mode=mode,
                )

        return One()

    def factory(self) -> ProbeFactory:
        @contextmanager
        def open_caller(arm: Arm) -> Iterator[Caller]:
            yield self.caller(arm)

        return open_caller


def control_key(panel: Panel) -> str:
    return next(a.key for a in panel.arms if a.arm == "control")


def test_every_arm_is_probed_once_in_pass_through_with_its_own_fields(panel: Panel) -> None:
    v = Vendor(dead=set())
    result = preflight(panel, v.factory(), run_id="drift-2026-12-preflight")
    assert [p.arm_key for p in result.probes] == [a.key for a in panel.arms]
    assert all(p.ok for p in result.probes) and not result.control_failed
    for (req, purpose, mode), arm in zip(v.seen, panel.arms, strict=True):
        assert purpose == "drift-preflight" and mode is Mode.PASSTHROUGH
        assert req.model == arm.explicit and req.extra == arm.extra
        assert req.max_tokens == PROBE_MAX_TOKENS


def test_a_dead_control_stops_the_run_and_says_why(panel: Panel) -> None:
    ck = control_key(panel)
    result = preflight(panel, Vendor(dead={ck}).factory(), run_id="r")
    assert result.control_failed
    (failed,) = result.failed
    assert failed.arm_key == ck and failed.status == "400"
    assert "non-serverless" in failed.detail and "non-serverless" in failed.line()


def test_a_retired_vendor_arm_is_reported_and_the_run_goes_ahead(panel: Panel) -> None:
    vendor_arm = next(a.key for a in panel.arms if a.arm != "control")
    result = preflight(panel, Vendor(dead={vendor_arm}).factory(), run_id="r")
    assert not result.control_failed
    assert [p.arm_key for p in result.failed] == [vendor_arm]


def test_a_provider_selection_probes_only_that_provider(panel: Panel) -> None:
    provider = panel.arms[0].provider
    result = preflight(panel, Vendor(dead=set()).factory(), run_id="r", providers=[provider])
    assert {p.arm_key for p in result.probes} == {
        a.key for a in panel.arms if a.provider == provider
    }

"""One short live call per arm before a monthly run spends anything (added 2026-11-07).

November 2026's run went ahead with a control that no longer existed: Together had taken
Llama-3.3-70B-Instruct-Turbo off its serverless tier on 2026-10-22, all 2,100 of the control's
calls came back 400 `model_not_available`, and the other seven arms spent US$15.89 on a month
that could not be judged, because drift is only declared against the control's change.
Nobody saw it for six days.

So the two kinds of arm are treated differently, as PLAN.md section 2.2 already implies:

- A vendor arm that fails is reported and the run goes ahead. A retired snapshot is a result,
  and "the runner keeps calling it and the error is the result" is the panel's own rule.
- The control failing stops the run before any vendor is called. Without it no arm can be
  judged (`drift_judged`), so every other call that month would be money spent on a record
  that cannot say anything about drift.

The probe is a fixed request with the arm's own `extra` and `omit`, so it fails for the same
reasons a real call would. It asks for one word and allows enough output for a model that
cannot be told not to think; whether any text comes back does not matter, only that the call
was accepted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from boundary import ChatRequest, Mode

from drift.panel import Arm, Panel
from drift.runner.run import Caller

PROBE_PROMPT = "Reply with the single word OK."
PROBE_MAX_TOKENS = 1024

# Opens one gateway for the probes of one arm; the context closes it.
ProbeFactory = Callable[[Arm], AbstractContextManager[Caller]]


@dataclass(frozen=True, slots=True)
class Probe:
    arm_key: str
    control: bool
    ok: bool
    status: str
    detail: str

    def line(self) -> str:
        kind = "control" if self.control else "arm"
        verdict = "ok" if self.ok else f"FAILED {self.status}"
        return f"{self.arm_key:<26} {kind:<7} {verdict}" + (
            f": {self.detail}" if self.detail else ""
        )


@dataclass(frozen=True, slots=True)
class Preflight:
    probes: tuple[Probe, ...]

    @property
    def control_failed(self) -> bool:
        return any(p.control and not p.ok for p in self.probes)

    @property
    def failed(self) -> list[Probe]:
        return [p for p in self.probes if not p.ok]


def probe(arm: Arm, caller: Caller, *, run_id: str) -> Probe:
    resp = caller.chat(
        ChatRequest(
            model=arm.explicit,
            system=None,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
            max_tokens=PROBE_MAX_TOKENS,
            temperature=None if "temperature" in arm.omit else 0.0,
            extra=arm.extra,
        ),
        purpose="drift-preflight",
        run_id=run_id,
        mode=Mode.PASSTHROUGH,
    )
    detail = "" if resp.ok else _reason(resp.raw)
    return Probe(arm.key, arm.arm == "control", resp.ok, str(resp.status), detail)


def _reason(raw: Any) -> str:
    """The vendor's own words for a failure, short: `error.message` where the body has one."""
    if isinstance(raw, dict):
        err = raw.get("error")
        if isinstance(err, dict) and err.get("message"):
            raw = err["message"]
        elif isinstance(err, str):
            raw = err
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    text = " ".join(str(raw).split()) if raw is not None else ""
    return text[:300]


def preflight(
    panel: Panel,
    open_caller: ProbeFactory,
    *,
    run_id: str,
    providers: Iterable[str] | None = None,
) -> Preflight:
    wanted = set(providers) if providers else None
    probes = []
    for arm in panel.arms:
        if wanted is not None and arm.provider not in wanted:
            continue
        with open_caller(arm) as caller:
            probes.append(probe(arm, caller, run_id=run_id))
    return Preflight(tuple(probes))

"""The monthly run: every item, k repeats, every arm, through boundary in pass-through mode.

What is held fixed (PLAN.md section 2.3): temperature, max_tokens per block, the system
prompt from the item, no tools, no caching, explicit model identifiers. The order of calls is
shuffled with a recorded seed so repeats of one item are spread across the run. The runner's
own cap aborts the run when the boundary ledger's spend for the run passes a multiple of the
expected cost; the run is then marked partial, never deleted.
"""

from __future__ import annotations

import datetime as dt
import platform
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from boundary import ChatRequest, ChatResponse, Mode
from boundary import __version__ as boundary_version

from drift import __version__ as drift_version
from drift.graders import grader
from drift.items import Item
from drift.panel import Arm, Panel
from drift.runner.records import (
    CallRecord,
    RunMeta,
    append_record,
    load_meta,
    read_records,
    records_path,
    save_meta,
)
from drift.suite import Suite

REQUEST_ID_HEADERS = ("request-id", "x-request-id", "cf-ray")


class Ledger(Protocol):
    def spend_usd(
        self, *, project: str | None, year_month: str | None = None, run_id: str | None = None
    ) -> float: ...


class Caller(Protocol):
    """What the runner needs from a boundary Gateway. Read-only members so any object with
    a compatible ledger satisfies it (the real Gateway, or a fake in tests)."""

    @property
    def project(self) -> str: ...

    @property
    def ledger(self) -> Ledger: ...

    def chat(
        self,
        request: ChatRequest,
        *,
        purpose: str,
        run_id: str | None = None,
        mode: Mode = Mode.STANDARD,
    ) -> ChatResponse: ...


@dataclass(frozen=True, slots=True)
class RunConfig:
    repeats: int = 5
    seed: int = 20260927
    temperature: float = 0.0
    max_tokens: dict[str, int] = field(
        default_factory=lambda: {
            "closed_form_reasoning": 512,
            "multiple_choice": 16,
            "instruction_following": 400,
            "structured_extraction": 400,
            "refusal_calibration": 300,
            "long_context_recall": 64,
            "paraphrase_robustness": 512,
        }
    )
    expected_cost_usd: float = 9.0
    abort_multiplier: float = 1.5
    items_limit: int | None = None  # dry runs: first N items per block after shuffling
    arm_keys: tuple[str, ...] | None = None
    pause_s: float = 0.0
    rerun_of: str | None = None


class RunAbortedError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan_calls(
    items: Iterable[Item], repeats: int, seed: int, arm_key: str
) -> list[tuple[str, int]]:
    """(item_id, repeat) pairs in a shuffled order that is fixed by seed and arm."""
    pairs = [(it.id, r) for it in items for r in range(repeats)]
    random.Random(f"{seed}:{arm_key}").shuffle(pairs)
    return pairs


def select_items(suite: Suite, limit: int | None, seed: int) -> list[Item]:
    if limit is None:
        return list(suite.items)
    out: list[Item] = []
    for block, items in sorted(suite.by_block().items()):
        rng = random.Random(f"{seed}:{block}")
        chosen = list(items)
        rng.shuffle(chosen)
        out.extend(chosen[:limit])
    return out


def _request_id(headers: dict[str, str] | object) -> str | None:
    if not isinstance(headers, dict):
        return None
    lower = {k.lower(): v for k, v in headers.items()}
    for h in REQUEST_ID_HEADERS:
        if h in lower:
            return str(lower[h])
    return None


def record_for(
    resp: ChatResponse, *, arm: Arm, item: Item, repeat: int, run_id: str, month: str
) -> CallRecord:
    correct: bool | None = None
    normalised: str | None = None
    detail: str | None = None
    if resp.ok and resp.text is not None:
        g = grader(item.grader).grade(resp.text, item.expected)
        correct, normalised, detail = g.correct, g.normalised, g.detail
    return CallRecord(
        ts_utc=utc_now(),
        run_id=run_id,
        month=month,
        arm_key=arm.key,
        provider=arm.provider,
        model_requested=resp.model_requested,
        model_returned=resp.model_returned,
        item_id=item.id,
        block=item.block,
        grader=item.grader,
        repeat=repeat,
        output=resp.text,
        finish_reason=resp.finish_reason,
        status=resp.status,
        error_type=None if resp.ok else str(resp.status),
        latency_ms=resp.latency_ms,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        cost_usd=resp.cost_usd,
        costed=resp.costed,
        ledger_id=resp.ledger_id,
        request_id=_request_id(dict(resp.headers)),
        correct=correct,
        normalised=normalised,
        detail=detail,
    )


def run_month(
    *,
    month: str,
    suite: Suite,
    panel: Panel,
    gateway: Caller,
    runs_root: Path,
    config: RunConfig,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> RunMeta:
    if not panel.ready:
        raise ValueError(
            "panel.yaml has identifiers still to choose; the panel is data, choose and date them first"
        )
    run_id = f"drift-{month}"
    arms = [a for a in panel.arms if config.arm_keys is None or a.key in config.arm_keys]
    items = select_items(suite, config.items_limit, config.seed)
    meta = load_meta(runs_root, month) or RunMeta(
        run_id=run_id,
        month=month,
        started_utc=utc_now(),
        suite_version=suite.version,
        suite_hash=suite.hash,
        panel_chosen=panel.chosen.isoformat() if panel.chosen else None,
        boundary_version=boundary_version,
        drift_version=drift_version,
        repeats=config.repeats,
        items=len(items),
        arms=[a.key for a in arms],
        seed=config.seed,
        expected_cost_usd=config.expected_cost_usd,
        abort_multiplier=config.abort_multiplier,
        rerun_of=config.rerun_of,
        runner={"python": platform.python_version(), "platform": platform.platform()},
    )
    if meta.suite_hash != suite.hash:
        raise ValueError(
            f"suite hash changed since this run started: {meta.suite_hash} vs {suite.hash}"
        )
    meta.status = "running"
    save_meta(runs_root, meta)

    by_id = {it.id: it for it in items}
    cap = config.expected_cost_usd * config.abort_multiplier
    try:
        for arm in arms:
            path = records_path(runs_root, month, arm.key)
            done = {(r.item_id, r.repeat) for r in read_records(path)}
            todo = [
                p for p in plan_calls(items, config.repeats, config.seed, arm.key) if p not in done
            ]
            log(f"{arm.key}: {len(todo)} calls to make, {len(done)} already recorded")
            for item_id, repeat in todo:
                spent = gateway.ledger.spend_usd(project=gateway.project, run_id=run_id)
                if spent > cap:
                    raise RunAbortedError(
                        f"spend US${spent:.2f} passed {config.abort_multiplier}x the expected US${config.expected_cost_usd:.2f}"
                    )
                item = by_id[item_id]
                resp = gateway.chat(
                    ChatRequest(
                        model=arm.explicit,
                        system=item.system,
                        messages=[{"role": "user", "content": item.prompt}],
                        max_tokens=config.max_tokens[item.block],
                        temperature=config.temperature,
                    ),
                    purpose="drift-run",
                    run_id=run_id,
                    mode=Mode.PASSTHROUGH,
                )
                append_record(
                    path,
                    record_for(resp, arm=arm, item=item, repeat=repeat, run_id=run_id, month=month),
                )
                meta.calls += 1
                if config.pause_s:
                    sleep(config.pause_s)
        meta.status = "complete"
    except RunAbortedError as e:
        meta.status = "partial"
        meta.reason = str(e)
        log(f"aborted: {e}")
    finally:
        meta.spent_usd = gateway.ledger.spend_usd(project=gateway.project, run_id=run_id)
        meta.finished_utc = utc_now()
        save_meta(runs_root, meta)
    return meta

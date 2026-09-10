"""The monthly run: every item, k repeats, every arm, through boundary in pass-through mode.

What is held fixed (PLAN.md section 2.3): temperature, max_tokens per block, the system
prompt from the item, no tools, no caching, explicit model identifiers. The order of calls is
shuffled with a recorded seed so repeats of one item are spread across the run.

One arm at a time (`run_arm`), each with its own directory, ledger and raw store, so the
arms of one provider can run as one GitHub Actions job while other providers run in parallel
(`run_month` loops over the arms selected and opens a gateway per arm). The runner's own cap
aborts an arm when the boundary ledger's spend for the run passes a multiple of that arm's
expected cost; the arm is then marked partial, never deleted.

Held-out items go through a second gateway whose raw store is not committed, and their
records carry the output's hash instead of the output.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import platform
import random
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from boundary import ChatRequest, ChatResponse, Mode
from boundary import __version__ as boundary_version
from boundary.config import PriceList

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

# PLAN.md section 6: the token assumptions behind the expected cost of a run. Replaced by the
# real usage in the record; used only to size the abort cap before the first call.
ASSUMED_INPUT_TOKENS = 700
ASSUMED_OUTPUT_TOKENS = 150


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
class Callers:
    """The gateway for public items and the one for held-out items (whose raw store is never
    committed). They may be the same object when nothing is held out."""

    public: Caller
    heldout: Caller

    def for_item(self, item: Item) -> Caller:
        return self.heldout if item.held_out else self.public


# Opens the callers for one arm; the context closes them. The CLI opens real Gateways with
# the arm's ledger and raw stores; tests return fakes.
CallerFactory = Callable[[Arm, Path], AbstractContextManager[Callers]]


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
    # Expected cost of the arms being run in this invocation. None means: estimate from the
    # price list and the token assumptions above.
    expected_cost_usd: float | None = None
    abort_multiplier: float = 1.5
    items_limit: int | None = None  # dry runs: first N items per block after shuffling
    arm_keys: tuple[str, ...] | None = None
    providers: tuple[str, ...] | None = None
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


def select_arms(panel: Panel, config: RunConfig) -> list[Arm]:
    return [
        a
        for a in panel.arms
        if (config.arm_keys is None or a.key in config.arm_keys)
        and (config.providers is None or a.provider in config.providers)
    ]


def estimate_arm_cost_usd(arm: Arm, calls: int, prices: PriceList | None) -> float | None:
    """What one arm's calls should cost at the price list, on the token assumptions. None when
    the model has no price (the caller then needs an explicit expected cost)."""
    if prices is None:
        return None
    entry = prices.lookup(arm.provider, arm.model)
    if entry is None:
        return None
    per_call = (ASSUMED_INPUT_TOKENS * entry.input + ASSUMED_OUTPUT_TOKENS * entry.output) / 1e6
    return round(calls * per_call, 6)


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
    output = resp.text
    output_sha256: str | None = None
    if item.held_out:
        # The grade stays; the text, its normalised form and the grader detail (which can
        # quote the expected value) do not.
        if output is not None:
            output_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        output = normalised = detail = None
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
        held_out=item.held_out,
        output=output,
        output_sha256=output_sha256,
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


def run_arm(
    *,
    month: str,
    suite: Suite,
    panel: Panel,
    arm: Arm,
    callers: Callers,
    runs_root: Path,
    config: RunConfig,
    expected_cost_usd: float,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> RunMeta:
    """Every planned call for one arm that is not yet recorded, then the arm's RUN.json."""
    run_id = f"drift-{month}"
    items = select_items(suite, config.items_limit, config.seed)
    meta = load_meta(runs_root, month, arm.key) or RunMeta(
        run_id=run_id,
        month=month,
        started_utc=utc_now(),
        suite_version=suite.version,
        suite_hash=suite.hash,
        heldout_items=sum(1 for it in items if it.held_out),
        panel_chosen=panel.chosen.isoformat() if panel.chosen else None,
        boundary_version=boundary_version,
        drift_version=drift_version,
        repeats=config.repeats,
        items=len(items),
        arms=[arm.key],
        seed=config.seed,
        expected_cost_usd=expected_cost_usd,
        abort_multiplier=config.abort_multiplier,
        rerun_of=config.rerun_of,
        runner={"python": platform.python_version(), "platform": platform.platform()},
    )
    if meta.suite_hash != suite.hash:
        raise ValueError(
            f"suite hash changed since this run started: {meta.suite_hash} vs {suite.hash}"
        )
    meta.status = "running"
    save_meta(runs_root, meta, arm.key)

    by_id = {it.id: it for it in items}
    cap = expected_cost_usd * config.abort_multiplier
    path = records_path(runs_root, month, arm.key)
    gateway = callers.public
    try:
        done = {(r.item_id, r.repeat) for r in read_records(path)}
        todo = [p for p in plan_calls(items, config.repeats, config.seed, arm.key) if p not in done]
        log(f"{arm.key}: {len(todo)} calls to make, {len(done)} already recorded")
        for item_id, repeat in todo:
            spent = gateway.ledger.spend_usd(project=gateway.project, run_id=run_id)
            if spent > cap:
                raise RunAbortedError(
                    f"spend US${spent:.2f} passed {config.abort_multiplier}x the expected US${expected_cost_usd:.2f}"
                )
            item = by_id[item_id]
            resp = callers.for_item(item).chat(
                ChatRequest(
                    model=arm.explicit,
                    system=item.system,
                    messages=[{"role": "user", "content": item.prompt}],
                    max_tokens=config.max_tokens[item.block],
                    temperature=config.temperature,
                    extra=arm.extra,
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
        log(f"{arm.key} aborted: {e}")
    finally:
        meta.spent_usd = gateway.ledger.spend_usd(project=gateway.project, run_id=run_id)
        meta.finished_utc = utc_now()
        save_meta(runs_root, meta, arm.key)
    return meta


def run_month(
    *,
    month: str,
    suite: Suite,
    panel: Panel,
    open_callers: CallerFactory,
    runs_root: Path,
    config: RunConfig,
    prices: PriceList | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> list[RunMeta]:
    """The selected arms, one after another, each with its own callers. Returns one RunMeta
    per arm; `summarise_month` folds them into the month's RUN.json."""
    if not panel.ready:
        raise ValueError(
            "panel.yaml has identifiers still to choose; the panel is data, choose and date them first"
        )
    arms = select_arms(panel, config)
    if not arms:
        raise ValueError("no arm matches the selection")
    n_calls = len(select_items(suite, config.items_limit, config.seed)) * config.repeats
    estimates = {a.key: estimate_arm_cost_usd(a, n_calls, prices) for a in arms}
    if config.expected_cost_usd is not None:
        # An explicit total for this invocation is split in proportion to the estimates, or
        # evenly when there is nothing to split by.
        known = {k: v for k, v in estimates.items() if v is not None}
        total = sum(known.values())
        expected = {
            a.key: (
                config.expected_cost_usd * known[a.key] / total
                if a.key in known and total > 0
                else config.expected_cost_usd / len(arms)
            )
            for a in arms
        }
    else:
        unpriced = [k for k, v in estimates.items() if v is None]
        if unpriced:
            raise ValueError(
                f"no price for {', '.join(unpriced)} in the price list; pass an explicit expected cost"
            )
        expected = {k: v for k, v in estimates.items() if v is not None}
    metas: list[RunMeta] = []
    for arm in arms:
        with open_callers(arm, runs_root / month / arm.key) as callers:
            metas.append(
                run_arm(
                    month=month,
                    suite=suite,
                    panel=panel,
                    arm=arm,
                    callers=callers,
                    runs_root=runs_root,
                    config=config,
                    expected_cost_usd=expected[arm.key],
                    sleep=sleep,
                    log=log,
                )
            )
    return metas

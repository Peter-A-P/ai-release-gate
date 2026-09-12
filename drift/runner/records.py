"""The run record: one JSON line per call, one directory per arm per month, plus RUN.json.

Layout under `drift/runs/<month>/`:

    RUN.json                    the month summary, written by `drift collect` from the arm files
    <arm>/RUN.json              that arm's run metadata (status, calls, spend)
    <arm>/records.jsonl         one CallRecord per call, append-only
    <arm>/ledger.sqlite         the boundary ledger for that arm's calls
    <arm>/raw/                  boundary's raw request and response store (public items)
    <arm>/raw-heldout/          the same for held-out items; gitignored, never committed

One directory per arm so the arms of different providers can run as parallel jobs on
GitHub Actions (each job under the six-hour limit) and be merged by copying directories.

Records are append-only (CLAUDE.md). A bad run is marked in RUN.json, never deleted. Each
record carries the graded outcome at record time and the boundary ledger id, so the two
stores can be joined. Replay regrades from `output` without any vendor call. For held-out
items `output` is replaced by its SHA-256 so the committed record reveals nothing about
the item; the grade is kept.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

RunStatus = Literal["running", "complete", "partial", "aborted"]
RECORDS_FILE = "records.jsonl"
META_FILE = "RUN.json"


class CallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts_utc: str
    run_id: str
    month: str
    arm_key: str
    provider: str
    model_requested: str
    model_returned: str | None
    item_id: str
    block: str
    grader: str
    repeat: int
    held_out: bool = False
    output: str | None
    output_sha256: str | None = None  # set for held-out items, whose output is not stored
    finish_reason: str | None
    status: int | str
    error_type: str | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    costed: bool
    ledger_id: int
    request_id: str | None
    correct: bool | None  # None when the call errored: not gradeable
    normalised: str | None
    detail: str | None

    @property
    def gradeable(self) -> bool:
        return self.correct is not None

    @property
    def truncated(self) -> bool:
        """The vendor stopped this call at the token budget rather than at the end of the
        answer. Each vendor has its own word for it."""
        return (self.finish_reason or "").lower() in TRUNCATED_FINISH_REASONS

    @property
    def errored(self) -> bool:
        """The call failed. Distinct from truncated, which is the budget binding rather than
        the vendor failing, and from ungradeable, which is either of them."""
        return self.error_type is not None


# What each vendor calls "I stopped because the budget ran out": Anthropic and Google say
# max_tokens, OpenAI says length, and Google's REST form shouts it. All three are the same
# event and all three are seen in drift/runs/2026-09-dry*.
TRUNCATED_FINISH_REASONS: frozenset[str] = frozenset({"max_tokens", "length"})


class RunMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    month: str
    started_utc: str
    finished_utc: str | None = None
    status: RunStatus = "running"
    reason: str | None = None
    suite_version: str
    suite_hash: str
    heldout_items: int = 0
    panel_chosen: str | None
    boundary_version: str
    drift_version: str
    repeats: int
    items: int
    arms: list[str]
    seed: int
    expected_cost_usd: float
    abort_multiplier: float
    spent_usd: float = 0.0
    calls: int = 0
    rerun_of: str | None = None
    runner: dict[str, str] = {}


def month_dir(runs_root: Path, month: str) -> Path:
    return runs_root / month


def arm_dir(runs_root: Path, month: str, arm_key: str) -> Path:
    return month_dir(runs_root, month) / arm_key


def records_path(runs_root: Path, month: str, arm_key: str) -> Path:
    return arm_dir(runs_root, month, arm_key) / RECORDS_FILE


def meta_path(runs_root: Path, month: str, arm_key: str | None = None) -> Path:
    if arm_key is None:
        return month_dir(runs_root, month) / META_FILE
    return arm_dir(runs_root, month, arm_key) / META_FILE


def read_records(path: Path) -> Iterator[CallRecord]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield CallRecord.model_validate_json(line)


def append_record(path: Path, record: CallRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json() + "\n")


def load_meta(runs_root: Path, month: str, arm_key: str | None = None) -> RunMeta | None:
    p = meta_path(runs_root, month, arm_key)
    if not p.is_file():
        return None
    return RunMeta.model_validate_json(p.read_text(encoding="utf-8"))


def save_meta(runs_root: Path, meta: RunMeta, arm_key: str | None = None) -> None:
    p = meta_path(runs_root, meta.month, arm_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def arms_recorded(runs_root: Path, month: str) -> list[str]:
    d = month_dir(runs_root, month)
    if not d.is_dir():
        return []
    return sorted(p.parent.name for p in d.glob(f"*/{RECORDS_FILE}"))


def summarise_month(runs_root: Path, month: str, expected_arms: Iterable[str]) -> RunMeta | None:
    """The month's RUN.json from the arm files: complete only when every expected arm is
    complete; otherwise partial, with the reasons joined. None when no arm has run."""
    metas = [
        (key, m)
        for key in arms_recorded(runs_root, month)
        if (m := load_meta(runs_root, month, key)) is not None
    ]
    if not metas:
        return None
    first = metas[0][1]
    recorded = {key for key, _ in metas}
    missing = sorted(set(expected_arms) - recorded)
    incomplete = [f"{key}: {m.reason or m.status}" for key, m in metas if m.status != "complete"]
    reasons = incomplete + [f"{key}: not run" for key in missing]
    summary = first.model_copy(
        update={
            "status": "complete" if not reasons else "partial",
            "reason": "; ".join(reasons) if reasons else None,
            "arms": sorted(recorded),
            "calls": sum(m.calls for _, m in metas),
            "spent_usd": round(sum(m.spent_usd for _, m in metas), 6),
            "expected_cost_usd": round(sum(m.expected_cost_usd for _, m in metas), 6),
            "started_utc": min(m.started_utc for _, m in metas),
            "finished_utc": max((m.finished_utc or "") for _, m in metas) or None,
        }
    )
    save_meta(runs_root, summary)
    return summary

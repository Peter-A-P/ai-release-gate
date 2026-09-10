"""The run record: one JSON line per call, one file per arm per month, plus RUN.json.

Records are append-only (CLAUDE.md). A bad run is marked in RUN.json, never deleted. Each
record carries the graded outcome at record time and the boundary ledger id, so the two
stores can be joined. Replay regrades from `output` without any vendor call.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

RunStatus = Literal["running", "complete", "partial", "aborted"]


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
    output: str | None
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


def records_path(runs_root: Path, month: str, arm_key: str) -> Path:
    return month_dir(runs_root, month) / f"{arm_key}.jsonl"


def meta_path(runs_root: Path, month: str) -> Path:
    return month_dir(runs_root, month) / "RUN.json"


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


def load_meta(runs_root: Path, month: str) -> RunMeta | None:
    p = meta_path(runs_root, month)
    if not p.is_file():
        return None
    return RunMeta.model_validate_json(p.read_text(encoding="utf-8"))


def save_meta(runs_root: Path, meta: RunMeta) -> None:
    p = meta_path(runs_root, meta.month)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def arms_recorded(runs_root: Path, month: str) -> list[str]:
    d = month_dir(runs_root, month)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.jsonl"))

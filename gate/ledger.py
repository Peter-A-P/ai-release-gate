"""The gate's ledger: one record per decision, appended and never edited (PLAN.md B2.4).

    gate/runs/ledger.jsonl      one GateRecord per line

Each record carries the content hashes a reader needs to reproduce the decision: the spec, the
frozen suite the items came from, the grader generation that scored them, and both sides'
sources. A mistake is corrected by a new record whose `supersedes` names the old one. The
record's own id is a hash of its content, so two runs of the same comparison under the same
spec produce the same id and a reader can see they are the same decision.

PLAN.md B3 names DuckDB and Parquet for storage. The record of decisions is this file, for the
same reason Part A's record is JSON lines: it is append-only in the plainest possible sense, it
diffs in git, and a reader needs nothing to open it. DuckDB arrives with the service (stage 6)
as a read model built from this file and from `drift/runs`, never as the thing written to.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gate import __version__
from gate.decision import Decision, SuiteResult

LEDGER_FILE = "ledger.jsonl"


class SuiteLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: str
    paired_items: int
    # None where there was nothing to compute: a suite with no gradeable item on a side. JSON
    # has no NaN, and a record that cannot be read back is not a record.
    baseline_accuracy: float | None
    candidate_accuracy: float | None
    difference: float | None
    lo: float | None
    hi: float | None
    delta: float
    p_inferior: float
    p_adjusted: float | None
    items_needed: int | None
    under_powered: bool
    effective_items: float | None
    verdict: str
    reasons: list[str]

    @classmethod
    def from_result(cls, r: SuiteResult) -> SuiteLine:
        d = r.decisive
        return cls(
            suite=r.suite,
            paired_items=d.paired_items,
            baseline_accuracy=_num(r.baseline.point),
            candidate_accuracy=_num(r.candidate.point),
            difference=_num(d.difference.point),
            lo=_num(d.difference.lo),
            hi=_num(d.difference.hi),
            delta=d.delta,
            p_inferior=d.p_inferior,
            p_adjusted=r.p_adjusted,
            items_needed=r.power.items if r.power is not None else None,
            under_powered=r.under_powered,
            effective_items=r.corrected.effective_items if r.corrected is not None else None,
            verdict=r.verdict,
            reasons=list(r.reasons),
        )


def _num(x: float) -> float | None:
    return None if math.isnan(x) else x


class GateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str
    ts_utc: str
    kind: Literal["compare"]
    gate_version: str
    spec_name: str
    spec_hash: str
    graders_hash: str
    baseline: dict[str, str]
    candidate: dict[str, str]
    suites: list[SuiteLine]
    lines: list[str]
    passed: bool
    reasons: list[str]
    supersedes: str | None = None

    @staticmethod
    def content_id(body: dict[str, object]) -> str:
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def record_for(
    decision: Decision,
    *,
    baseline: dict[str, str],
    candidate: dict[str, str],
    supersedes: str | None = None,
    now: datetime | None = None,
) -> GateRecord:
    from drift.graders import GRADERS_HASH

    ts = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body: dict[str, object] = {
        "kind": "compare",
        "gate_version": __version__,
        "spec_name": decision.spec_name,
        "spec_hash": decision.spec_hash,
        "graders_hash": GRADERS_HASH,
        "baseline": baseline,
        "candidate": candidate,
        "suites": [SuiteLine.from_result(r).model_dump(mode="json") for r in decision.suites],
        "lines": [ln.reason for ln in decision.lines],
        "passed": decision.passed,
        "reasons": list(decision.reasons),
        "supersedes": supersedes,
    }
    # The timestamp is outside the id on purpose: the same decision made twice is the same
    # decision, and the id should say so.
    return GateRecord.model_validate(
        {**body, "record_id": GateRecord.content_id(body), "ts_utc": ts}
    )


def append(path: Path, record: GateRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json() + "\n")


def read(path: Path) -> Iterator[GateRecord]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield GateRecord.model_validate_json(line)

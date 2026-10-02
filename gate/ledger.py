"""The gate's ledger: one record per decision, appended and never edited (PLAN.md B2.4).

    gate/runs/ledger.jsonl      one GateRecord per line

Each record carries the content hashes a reader needs to reproduce the decision: the spec, the
frozen suite the items came from, the grader generation that scored them, and both sides'
sources. A mistake is corrected by a new record whose `supersedes` names the old one. The
record's own id is a hash of its content, so two runs of the same comparison under the same
spec produce the same id and a reader can see they are the same decision.

A pull request's record also says where and at what cost it was decided: the repository, the
pull request, the commit, the run, and each side's calls, cost, latency and accuracy with its
interval (stage 7). Those are outside the id, like the timestamp, because they describe the
occasion rather than the decision; a re-run that decides the same thing is the same decision on
another occasion. The judges that graded it are inside the id, because a different licence is
a different decision. All of these are left out of the line when absent, so the records written
before they existed read back, and re-hash, exactly as they were.

PLAN.md B3 names DuckDB and Parquet for storage. The record of decisions is this file, for the
same reason Part A's record is JSON lines: it is append-only in the plainest possible sense, it
diffs in git, and a reader needs nothing to open it. DuckDB arrives with the service (stage 6)
as a read model built from this file and from `drift/runs`, never as the thing written to.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from gate import __version__
from gate.decision import Decision, SuiteResult
from gate.judge.calibration import CorrectedRate
from gate.outcomes import Side

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


class SideSuite(BaseModel):
    """One side of a decision on one suite, as it was measured on this occasion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: str
    items: int
    accuracy: float | None
    lo: float | None
    hi: float | None
    ungradeable_items: int
    calls: int
    latency_p50_ms: float | None
    cost_usd: float
    uncosted_calls: int
    # For a judge-graded suite, the accuracy with the judge's own error taken out
    # (Rogan-Gladen, `gate.judge.calibration.corrected_rate`), beside the raw call above.
    # Kept from 2026-10-02; absent from the line when there is none.
    corrected: float | None = None
    corrected_lo: float | None = None
    corrected_hi: float | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        for key in ("corrected", "corrected_lo", "corrected_hi"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class JudgeLine(BaseModel):
    """A judge that graded a suite, with the licence it was graded under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: str
    judge: str
    task: str
    max_tokens: int
    kappa: float
    rubric: str


class Occasion(BaseModel):
    """Where a decision was made and what it cost. Outside the record's id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = ""
    pull_request: int | None = None
    head_sha: str = ""
    run_url: str = ""
    fresh_calls: int = 0
    cache_hits: int = 0
    spent_usd: float = 0.0
    sides: dict[str, list[SideSuite]] = {}


def side_suites(
    side: Side,
    *,
    resamples: int,
    seed: int,
    corrected: Mapping[str, CorrectedRate] | None = None,
) -> list[SideSuite]:
    """Each suite of a side as measured. `corrected` holds the judge-corrected rate for the
    suites a judge graded, from the same function the pull-request comment prints."""
    out = []
    for key, s in side.suites.items():
        acc = s.accuracy(resamples=resamples, seed=seed)
        c = (corrected or {}).get(key)
        fixed = c.corrected if c is not None and not c.degenerate and c.corrected.n else None
        out.append(
            SideSuite(
                suite=key,
                items=s.items,
                accuracy=_num(acc.point) if acc.n else None,
                lo=_num(acc.lo) if acc.n else None,
                hi=_num(acc.hi) if acc.n else None,
                ungradeable_items=s.ungradeable_items,
                calls=s.calls,
                latency_p50_ms=_num(s.latency_p50_ms),
                cost_usd=s.cost_usd,
                uncosted_calls=s.uncosted_calls,
                corrected=_num(fixed.point) if fixed is not None else None,
                corrected_lo=_num(fixed.lo) if fixed is not None else None,
                corrected_hi=_num(fixed.hi) if fixed is not None else None,
            )
        )
    return out


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
    judges: list[JudgeLine] | None = None
    occasion: Occasion | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        # Absent, not null: the records from before these fields existed stay byte for byte.
        data: dict[str, object] = handler(self)
        for key in ("judges", "occasion"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    def content(self) -> dict[str, object]:
        """What the id is a hash of: everything but the id, the time and the occasion."""
        body = self.model_dump(mode="json")
        for key in ("record_id", "ts_utc", "occasion"):
            body.pop(key, None)
        return body

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
    judges: list[JudgeLine] | None = None,
    occasion: Occasion | None = None,
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
    if judges is not None:
        body["judges"] = [j.model_dump(mode="json") for j in judges]
    # The timestamp and the occasion are outside the id on purpose: the same decision made twice
    # is the same decision, and the id should say so.
    return GateRecord.model_validate(
        {
            **body,
            "record_id": GateRecord.content_id(body),
            "ts_utc": ts,
            "occasion": occasion,
        }
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


def occasion_key(r: GateRecord) -> tuple[str, str]:
    """One decision on one occasion. The id alone would fold two runs that decided the same
    thing into one, and a count of decisions made would come out short."""
    run = r.occasion.run_url if r.occasion is not None else ""
    return (r.record_id, run or r.ts_utc)


def import_records(path: Path, records: Iterator[GateRecord] | list[GateRecord]) -> int:
    """Append the records not already in the ledger, in the order given. Returns how many.

    A record whose id does not match its content is refused rather than imported: an id is the
    one thing a reader checks a record by, and a ledger that takes a wrong one on trust is not
    content-addressed any more."""
    have = {occasion_key(r) for r in read(path)}
    added = 0
    for r in records:
        if GateRecord.content_id(r.content()) != r.record_id:
            raise ValueError(f"record {r.record_id}: its id does not match its content")
        if occasion_key(r) in have:
            continue
        append(path, r)
        have.add(occasion_key(r))
        added += 1
    return added

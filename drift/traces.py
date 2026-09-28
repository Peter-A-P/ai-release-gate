"""OpenTelemetry traces of a run, rebuilt from its boundary ledgers (PLAN.md B8.1 step 9).

    uv run drift traces --month 2026-09 --out traces/2026-09.otlp.jsonl

Every vendor call already has a ledger row: when it started, how long it took, the model asked
for and the model that answered, tokens, cost, status, retries. That row is the record. A trace
is a view of it, so this writes one span per row in OTLP/JSON, the OpenTelemetry protocol's
own file encoding, which any collector reads with its `otlpjsonfile` receiver and Jaeger or
Grafana Tempo then show. One trace per arm: a root span over the arm's whole run, and one client
span per call beneath it.

Why rebuilt rather than exported live. The runs are pinned to boundary v0.1.0, whose telemetry
exports to the console or nowhere (OTLP arrives with project 04's Part B), and a live exporter
would need a collector reachable from GitHub's runners. Rebuilding from the ledger needs
neither, works for every run already committed, and cannot disagree with the record, because it
is the record. What it cannot show is anything the ledger does not hold: there is no span for
grading, and no finish reason.

No content, by the same rule boundary applies to its live spans: every call span's attributes
are drawn from `boundary.telemetry.ALLOWED_ATTRIBUTES`, and a test holds them to it. No prompt,
no answer, no hash of either.

Deterministic: the same ledgers always give the same bytes. Ids come from the ledger when
telemetry was on, and otherwise are derived from the run, the arm and the row id.

Standard library only, so the monthly job installs nothing it did not install before.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from boundary.telemetry import ALLOWED_ATTRIBUTES

# OTLP enums (opentelemetry/proto/trace/v1/trace.proto).
SPAN_KIND_INTERNAL = 1
SPAN_KIND_CLIENT = 3
STATUS_CODE_ERROR = 2

# Spans per line. A collector's file receiver reads a line at most 1 MiB long by default
# (`max_log_size`) and drops the rest without a word: one arm on one line is about 3 MB, and a
# collector given it received nothing. A call span is about 1.4 kB, so 400 fit with room.
SPANS_PER_REQUEST = 400

# The columns read, and nothing else: request_sha256, response_sha256 and raw_path stay behind.
COLUMNS = (
    "id",
    "ts_utc",
    "boundary_version",
    "project",
    "purpose",
    "run_id",
    "mode",
    "provider",
    "alias",
    "model_requested",
    "model_returned",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "costed",
    "cached",
    "latency_ms",
    "http_status",
    "error_type",
    "retries",
    "trace_id",
    "span_id",
)


def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Every row of one boundary ledger, oldest first. Opened immutable: reading the record must
    not write to it, and a normal open would write back the -wal and -shm sidecars."""
    uri = f"file:{path.resolve()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(f"SELECT {', '.join(COLUMNS)} FROM ledger ORDER BY id")
        return [dict(zip(COLUMNS, row, strict=True)) for row in cur]
    finally:
        con.close()


def _hex(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def _nanos(ts_utc: str) -> int:
    """boundary's `2026-09-13T02:04:47.210Z`, the moment the call started, in Unix nanoseconds.
    Integer arithmetic throughout, so no float rounding moves a timestamp."""
    dt = datetime.strptime(ts_utc, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = dt - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _value(v: str | int | float | bool) -> dict[str, Any]:
    # bool before int, since a bool is an int. OTLP/JSON writes 64-bit integers as strings.
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": v}


def _attributes(attrs: dict[str, str | int | float | bool | None]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _value(v)} for k, v in attrs.items() if v is not None]


def call_attributes(row: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    """The attributes boundary's own live span carries for a call, from its ledger row."""
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.system": row["provider"],
        "gen_ai.request.model": row["model_requested"],
        "gen_ai.response.model": row["model_returned"],
        "gen_ai.usage.input_tokens": row["input_tokens"],
        "gen_ai.usage.output_tokens": row["output_tokens"],
        "http.response.status_code": row["http_status"],
        "error.type": row["error_type"],
        "boundary.project": row["project"],
        "boundary.purpose": row["purpose"],
        "boundary.run_id": row["run_id"],
        "boundary.mode": row["mode"],
        "boundary.alias": row["alias"],
        "boundary.provider": row["provider"],
        "boundary.cost_usd": row["cost_usd"],
        "boundary.costed": bool(row["costed"]),
        "boundary.cached": bool(row["cached"]),
        "boundary.retries": row["retries"],
        "boundary.latency_ms": row["latency_ms"],
        "boundary.ledger_id": row["id"],
        "boundary.version": row["boundary_version"],
    }


def arm_trace(
    arm: str, rows: Sequence[dict[str, Any]], *, per_request: int = SPANS_PER_REQUEST
) -> list[dict[str, Any]]:
    """One arm's calls as one trace, a root span over the arm and a client span per call, in
    OTLP ExportTraceServiceRequests of at most `per_request` spans each."""
    if not rows:
        raise ValueError(f"{arm}: the ledger holds no calls")
    run_id = rows[0]["run_id"] or ""
    trace_id = rows[0]["trace_id"] or _hex(f"trace/{run_id}/{arm}", 32)
    root_id = _hex(f"root/{run_id}/{arm}", 16)
    spans: list[dict[str, Any]] = []
    first = last = None
    for row in rows:
        start = _nanos(row["ts_utc"])
        end = start + round((row["latency_ms"] or 0.0) * 1_000_000)
        first = start if first is None else min(first, start)
        last = end if last is None else max(last, end)
        attrs = call_attributes(row)
        span: dict[str, Any] = {
            "traceId": trace_id,
            "spanId": row["span_id"] or _hex(f"span/{run_id}/{arm}/{row['id']}", 16),
            "parentSpanId": root_id,
            "name": "boundary.chat",
            "kind": SPAN_KIND_CLIENT,
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
            "attributes": _attributes(attrs),
        }
        if row["error_type"]:
            span["status"] = {"code": STATUS_CODE_ERROR, "message": row["error_type"]}
        spans.append(span)
    root = {
        "traceId": trace_id,
        "spanId": root_id,
        "name": f"drift.arm {arm}",
        "kind": SPAN_KIND_INTERNAL,
        "startTimeUnixNano": str(first),
        "endTimeUnixNano": str(last),
        "attributes": _attributes({"boundary.run_id": run_id, "drift.arm": arm}),
    }
    resource = {
        "attributes": _attributes(
            {"service.name": rows[0]["project"], "service.version": rows[0]["boundary_version"]}
        )
    }
    scope = {"name": "boundary", "version": rows[0]["boundary_version"]}
    every = [root, *spans]
    return [
        {
            "resourceSpans": [
                {
                    "resource": resource,
                    "scopeSpans": [{"scope": scope, "spans": every[i : i + per_request]}],
                }
            ]
        }
        for i in range(0, len(every), per_request)
    ]


def month_ledgers(runs: Path, month: str) -> list[tuple[str, Path]]:
    """(arm, ledger) for every arm directory of a month, in name order."""
    base = runs / month
    found = sorted((p.parent.name, p) for p in base.glob("*/ledger.sqlite"))
    if not found:
        raise FileNotFoundError(f"no arm ledgers under {base}")
    return found


def month_traces(runs: Path, month: str) -> Iterator[dict[str, Any]]:
    for arm, ledger in month_ledgers(runs, month):
        yield from arm_trace(arm, read_ledger(ledger))


def write_traces(requests: Iterator[dict[str, Any]], out: Path) -> tuple[int, int]:
    """JSON Lines, one ExportTraceServiceRequest a line, which is the layout a collector's
    `otlpjsonfile` receiver reads. Returns (traces, spans)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    trace_ids: set[str] = set()
    spans = 0
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for request in requests:
            f.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
            for r in request["resourceSpans"]:
                for s in r["scopeSpans"]:
                    spans += len(s["spans"])
                    trace_ids.update(span["traceId"] for span in s["spans"])
    return len(trace_ids), spans


def undeclared_attributes(request: dict[str, Any]) -> set[str]:
    """Call-span attribute keys outside boundary's allow list. Empty, or the export is wrong."""
    keys: set[str] = set()
    for r in request["resourceSpans"]:
        for s in r["scopeSpans"]:
            for span in s["spans"]:
                if span["kind"] == SPAN_KIND_CLIENT:
                    keys.update(a["key"] for a in span["attributes"])
    return keys - ALLOWED_ATTRIBUTES

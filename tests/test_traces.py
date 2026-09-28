"""The OpenTelemetry export: a faithful, contentless view of the committed ledgers."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any

from boundary.telemetry import ALLOWED_ATTRIBUTES
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from drift.traces import (
    SPAN_KIND_CLIENT,
    arm_trace,
    month_ledgers,
    month_traces,
    read_ledger,
    undeclared_attributes,
    write_traces,
)

RUNS = Path(__file__).resolve().parent.parent / "drift" / "runs"
# A committed month small enough to read whole: eight arms of seven calls.
MONTH = "2026-09-dry"


def _spans(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        span
        for q in requests
        for r in q["resourceSpans"]
        for s in r["scopeSpans"]
        for span in s["spans"]
    ]


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_every_ledger_row_is_one_call_span_under_one_root_per_arm() -> None:
    for arm, ledger in month_ledgers(RUNS, MONTH):
        rows = read_ledger(ledger)
        spans = _spans(arm_trace(arm, rows))
        roots = [s for s in spans if "parentSpanId" not in s]
        calls = [s for s in spans if s["kind"] == SPAN_KIND_CLIENT]
        assert len(roots) == 1 and len(calls) == len(rows) == 7
        assert {s["traceId"] for s in spans} == {roots[0]["traceId"]}
        assert {s["parentSpanId"] for s in calls} == {roots[0]["spanId"]}
        assert len({s["spanId"] for s in spans}) == len(spans)
        assert sorted(int(_attrs(s)["boundary.ledger_id"]) for s in calls) == [
            r["id"] for r in rows
        ]


def test_a_span_is_timed_and_attributed_exactly_as_its_ledger_row() -> None:
    arm, ledger = month_ledgers(RUNS, MONTH)[0]
    rows = {r["id"]: r for r in read_ledger(ledger)}
    for span in _spans(arm_trace(arm, list(rows.values()))):
        if span["kind"] != SPAN_KIND_CLIENT:
            continue
        a = _attrs(span)
        row = rows[int(a["boundary.ledger_id"])]
        took = int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])
        assert took == round(row["latency_ms"] * 1_000_000)
        assert a["gen_ai.request.model"] == row["model_requested"]
        assert a["gen_ai.response.model"] == row["model_returned"]
        assert int(a["gen_ai.usage.output_tokens"]) == row["output_tokens"]
        assert a["boundary.cost_usd"] == row["cost_usd"]
        assert int(a["http.response.status_code"]) == row["http_status"]


def test_no_content_leaves_the_ledger(tmp_path: Path) -> None:
    out = tmp_path / "t.jsonl"
    write_traces(month_traces(RUNS, MONTH), out)
    text = out.read_text(encoding="utf-8")
    for q in (json.loads(line) for line in text.splitlines()):
        assert undeclared_attributes(q) == set()
    # Nothing that points at the content either: no request or response hash, no raw store path.
    for _, ledger in month_ledgers(RUNS, MONTH):
        con = sqlite3.connect(f"file:{ledger.resolve()}?mode=ro&immutable=1", uri=True)
        try:
            hashes = con.execute("SELECT request_sha256, response_sha256 FROM ledger").fetchall()
        finally:
            con.close()
        assert hashes and all(h not in text for pair in hashes for h in pair if h)
    assert "raw/" not in text and "sha256" not in text


def test_the_allow_list_check_catches_an_extra_attribute() -> None:
    arm, ledger = month_ledgers(RUNS, MONTH)[0]
    request = arm_trace(arm, read_ledger(ledger))[0]
    call = next(s for s in _spans([request]) if s["kind"] == SPAN_KIND_CLIENT)
    call["attributes"].append({"key": "gen_ai.prompt", "value": {"stringValue": "hello"}})
    assert undeclared_attributes(request) == {"gen_ai.prompt"}
    assert "gen_ai.prompt" not in ALLOWED_ATTRIBUTES


def test_the_export_is_deterministic_and_leaves_the_ledgers_untouched(tmp_path: Path) -> None:
    ledgers = [p for _, p in month_ledgers(RUNS, MONTH)]
    # Sidecars may already be there from any earlier ordinary open; the export must not add or
    # touch one, which is what an ordinary open would do.
    sidecars = [p.with_name(p.name + x) for p in ledgers for x in ("-wal", "-shm")]

    def state(p: Path) -> tuple[int, bytes] | None:
        return (p.stat().st_mtime_ns, p.read_bytes()) if p.exists() else None

    before = {p: state(p) for p in [*ledgers, *sidecars]}
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    assert write_traces(month_traces(RUNS, MONTH), a) == (8, 64)
    write_traces(month_traces(RUNS, MONTH), b)
    assert a.read_bytes() == b.read_bytes()
    assert {p: state(p) for p in [*ledgers, *sidecars]} == before


def test_a_long_arm_is_split_into_requests_a_collector_reads_whole() -> None:
    arm, ledger = month_ledgers(RUNS, MONTH)[0]
    requests = arm_trace(arm, read_ledger(ledger), per_request=3)
    assert [len(_spans([q])) for q in requests] == [3, 3, 2]
    assert len({s["traceId"] for s in _spans(requests)}) == 1
    # The real month: every line under the file receiver's 1 MiB default.
    for q in month_traces(RUNS, "2026-09"):
        assert len(json.dumps(q, separators=(",", ":")).encode("utf-8")) < 1024 * 1024


def _to_proto_json(value: Any, key: str = "") -> Any:
    # OTLP/JSON writes trace and span ids as hex; protobuf's own JSON parser wants bytes as
    # base64. The collector accepts the hex, so only this test converts.
    if isinstance(value, dict):
        return {k: _to_proto_json(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_proto_json(v) for v in value]
    if key in ("traceId", "spanId", "parentSpanId"):
        return base64.b64encode(bytes.fromhex(value)).decode("ascii")
    return value


def test_every_request_parses_under_opentelemetrys_own_protocol_definitions() -> None:
    for q in month_traces(RUNS, MONTH):
        msg = trace_service_pb2.ExportTraceServiceRequest()
        # ignore_unknown_fields=False: a misspelt field is an error, not silently dropped.
        json_format.ParseDict(_to_proto_json(q), msg, ignore_unknown_fields=False)
        spans = [s for r in msg.resource_spans for ss in r.scope_spans for s in ss.spans]
        assert all(len(s.trace_id) == 16 and len(s.span_id) == 8 for s in spans)
        assert all(s.end_time_unix_nano >= s.start_time_unix_nano > 0 for s in spans)

"""The FastAPI app: pages and JSON over the read model. GET only; nothing here writes.

    uv run gate serve                       # http://127.0.0.1:8000
    uv run gate export --out site/          # the same responses as files, for static hosting

Every response is one entry of `ROUTES`, rendered to bytes from the read model. The app serves
those bytes and `service.export` writes them to files, so the published site is the service's
output by construction and never a second implementation of it (PLAN.md B8.1).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response

from drift.analysis.stats import Estimate
from gate.judge import calibration as calib
from gate.redteam.suite import SUITES
from service import pages
from service.readmodel import Holder, ReadModel, build

ROOT = Path(__file__).resolve().parent.parent


def estimate(x: Estimate) -> dict[str, Any]:
    """An interval as JSON. NaN has no JSON form, so an undefined bound is null."""

    def num(v: float) -> float | None:
        return None if math.isnan(v) else round(v, 6)

    return {"point": num(x.point), "lo": num(x.lo), "hi": num(x.hi), "n": x.n}


def drift_json(m: ReadModel) -> dict[str, Any]:
    return {
        "control_arm": m.control_key,
        "runs": [
            {
                "run": r.label,
                "run_id": r.meta.run_id,
                "started_utc": r.meta.started_utc,
                "suite_hash": r.meta.suite_hash,
                "calls": r.meta.calls,
                "spent_usd": r.meta.spent_usd,
                "arms": {
                    k: {
                        "accuracy": estimate(a.accuracy),
                        "same_day_flip_rate": estimate(a.same_day_flip_rate),
                        "refusal_rate_should_answer": estimate(a.refusal_rate_should_answer),
                        "refusal_rate_should_refuse": estimate(a.refusal_rate_should_refuse),
                        "error_rate": estimate(a.error_rate),
                        "truncation_rate": estimate(a.truncation_rate),
                        "accuracy_by_block": {
                            b: estimate(v) for b, v in a.accuracy_by_block.items()
                        },
                        "latency_p50_ms": a.latency_p50_ms,
                        "latency_p95_ms": a.latency_p95_ms,
                        "cost_usd": a.cost_usd,
                    }
                    for k, a in sorted(r.arms.items())
                },
            }
            for r in m.runs
        ],
    }


def _judges_json(judges: dict[str, calib.Calibration]) -> dict[str, Any]:
    return {
        key: {
            t.task: {
                "usable": t.usable,
                "kappa": estimate(t.kappa),
                "alpha": estimate(t.alpha),
                "sensitivity": estimate(t.sensitivity),
                "specificity": estimate(t.specificity),
                "raw_agreement": t.raw_agreement,
                "rubric_hash": t.rubric_hash,
            }
            for t in c.tasks
        }
        for key, c in sorted(judges.items())
    }


def judge_json(m: ReadModel) -> dict[str, Any]:
    """On the first hundred, as published."""
    return _judges_json(m.judges)


def judge_multipart_json(m: ReadModel) -> dict[str, Any]:
    """On the multi-part stratum, licensed separately."""
    return _judges_json(m.judges_multipart)


def redteam_json(m: ReadModel) -> dict[str, Any]:
    return {
        "suite_hash": m.redteam_suite_hash,
        "runs": {
            run_id: {
                "cost_usd": s.cost_usd,
                "stale_answers": s.stale,
                "arms": {
                    a: {
                        x: {
                            "failure_rate": estimate(s.cells[(a, x)].rate),
                            "failed": s.cells[(a, x)].failed,
                            "graded": s.cells[(a, x)].graded,
                            "ungradeable": s.cells[(a, x)].ungradeable,
                        }
                        for x in SUITES
                    }
                    for a in s.arms
                },
            }
            for run_id, s in sorted(m.redteam.items())
        },
    }


def costs_json(m: ReadModel) -> list[dict[str, Any]]:
    return m.query(
        "SELECT run_label, arm_key, block, count(*) AS calls, sum(cost_usd) AS cost_usd, "
        "sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens "
        "FROM calls GROUP BY ALL ORDER BY run_label, arm_key, block"
    )


def gate_json(m: ReadModel) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in m.decisions]


def build_json(m: ReadModel) -> dict[str, Any]:
    """What the pages were built from: the uptime ping's target, and an auditor's first check."""
    return {"ok": True, "commit": m.commit, "built_utc": m.built_utc, "runs": len(m.runs)}


HTML = "text/html; charset=utf-8"
JSON = "application/json"


@dataclass(frozen=True, slots=True)
class Route:
    path: str  # where the page is served, by the app and on the static site
    file: str  # where the export writes it, relative to the site root
    media_type: str
    render: Callable[[ReadModel], bytes]
    # Older paths the app still answers with the same bytes. Not exported: the static site
    # publishes JSON under /data/, because Azure Static Web Apps reserves /api/ for Functions.
    aliases: tuple[str, ...] = ()


def _page(path: str, title: str, body: Callable[[ReadModel], str]) -> Callable[[ReadModel], bytes]:
    return lambda m: pages.page(m, path, title, body(m)).encode("utf-8")


def _json(value: Callable[[ReadModel], Any]) -> Callable[[ReadModel], bytes]:
    return lambda m: json.dumps(
        value(m), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


ROUTES: tuple[Route, ...] = (
    Route("/", "index.html", HTML, _page("/", "Overview", pages.overview)),
    Route("/drift", "drift.html", HTML, _page("/drift", "Drift record", pages.drift_page)),
    Route("/costs", "costs.html", HTML, _page("/costs", "Cost", pages.costs_page)),
    Route("/gate", "gate.html", HTML, _page("/gate", "Gate decisions", pages.gate_page)),
    Route("/judge", "judge.html", HTML, _page("/judge", "Judge calibration", pages.judge_page)),
    Route("/redteam", "redteam.html", HTML, _page("/redteam", "Red team", pages.redteam_page)),
    Route("/data/drift.json", "data/drift.json", JSON, _json(drift_json), ("/api/drift",)),
    Route("/data/costs.json", "data/costs.json", JSON, _json(costs_json), ("/api/costs",)),
    Route("/data/gate.json", "data/gate.json", JSON, _json(gate_json), ("/api/gate",)),
    Route("/data/judge.json", "data/judge.json", JSON, _json(judge_json), ("/api/judge",)),
    Route(
        "/data/judge-multipart.json", "data/judge-multipart.json", JSON, _json(judge_multipart_json)
    ),
    Route("/data/redteam.json", "data/redteam.json", JSON, _json(redteam_json), ("/api/redteam",)),
    Route("/data/build.json", "data/build.json", JSON, _json(build_json), ("/healthz",)),
)


def create_app(root: Path = ROOT, *, builder: Callable[[Path], ReadModel] = build) -> FastAPI:
    holder = Holder(root, builder=builder)
    app = FastAPI(
        title="AI Release Gate",
        description="Read-only: the drift record, the gate's decisions, judge calibration, red team.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    def handler(route: Route) -> Callable[[], Response]:
        def respond() -> Response:
            return Response(route.render(holder.current()), media_type=route.media_type)

        respond.__name__ = "get_" + (route.file.replace("/", "_").replace(".", "_"))
        return respond

    for route in ROUTES:
        for path in (route.path, *route.aliases):
            app.get(path, response_class=Response)(handler(route))
    return app


def app_from_env() -> FastAPI:
    """For `uvicorn service.app:app`: the repository is GATE_ROOT, or this checkout."""
    return create_app(Path(os.environ.get("GATE_ROOT", str(ROOT))))


def __getattr__(name: str) -> Any:
    # Built on first access, not on import, so importing the module in a test costs nothing.
    if name == "app":
        return app_from_env()
    raise AttributeError(name)

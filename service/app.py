"""The FastAPI app: pages and a JSON API over the read model. GET only; nothing here writes.

uv run gate serve                       # http://127.0.0.1:8000
uv run uvicorn service.app:app          # the same, as the container runs it
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from drift.analysis.stats import Estimate
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


def judge_json(m: ReadModel) -> dict[str, Any]:
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
        for key, c in sorted(m.judges.items())
    }


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


def create_app(root: Path = ROOT, *, builder: Callable[[Path], ReadModel] = build) -> FastAPI:
    holder = Holder(root, builder=builder)
    app = FastAPI(
        title="AI Release Gate",
        description="Read-only: the drift record, the gate's decisions, judge calibration, red team.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    def html(
        path: str, title: str, render: Callable[[ReadModel], str]
    ) -> Callable[[], HTMLResponse]:
        def handler() -> HTMLResponse:
            m = holder.current()
            return HTMLResponse(pages.page(m, path, title, render(m)))

        handler.__name__ = f"page_{title.lower().replace(' ', '_')}"
        return handler

    for path, title, render in (
        ("/", "Overview", pages.overview),
        ("/drift", "Drift record", pages.drift_page),
        ("/costs", "Cost", pages.costs_page),
        ("/gate", "Gate decisions", pages.gate_page),
        ("/judge", "Judge calibration", pages.judge_page),
        ("/redteam", "Red team", pages.redteam_page),
    ):
        app.get(path, response_class=HTMLResponse)(html(path, title, render))

    @app.get("/api/drift")
    def api_drift() -> dict[str, Any]:
        return drift_json(holder.current())

    @app.get("/api/costs")
    def api_costs() -> list[dict[str, Any]]:
        return holder.current().query(
            "SELECT run_label, arm_key, block, count(*) AS calls, sum(cost_usd) AS cost_usd, "
            "sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens "
            "FROM calls GROUP BY ALL ORDER BY run_label, arm_key, block"
        )

    @app.get("/api/gate")
    def api_gate() -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in holder.current().decisions]

    @app.get("/api/judge")
    def api_judge() -> dict[str, Any]:
        return judge_json(holder.current())

    @app.get("/api/redteam")
    def api_redteam() -> dict[str, Any]:
        return redteam_json(holder.current())

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        m = holder.current()
        return {"ok": True, "commit": m.commit, "built_utc": m.built_utc, "runs": len(m.runs)}

    return app


def app_from_env() -> FastAPI:
    """For `uvicorn service.app:app`: the repository is GATE_ROOT, or this checkout."""
    return create_app(Path(os.environ.get("GATE_ROOT", str(ROOT))))


def __getattr__(name: str) -> Any:
    # Built on first access, not on import, so importing the module in a test costs nothing.
    if name == "app":
        return app_from_env()
    raise AttributeError(name)

"""The dashboard (PLAN.md B8): every page loads, nothing writes, and every number on a page is
the number the committed reports print, because a dashboard that disagrees with the record is
worse than no dashboard."""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from drift.analysis.report import readme_rows
from drift.items import TYPOGRAPHIC
from gate.redteam import report as rt_report
from gate.redteam import run as rt_run
from gate.redteam.suite import SUITES, load_suite
from service import app as service_app
from service import readmodel

ROOT = Path(__file__).resolve().parent.parent
RUN = "2026-09"
PAGES = ("/", "/drift", "/costs", "/gate", "/judge", "/redteam")
APIS = ("/api/drift", "/api/costs", "/api/gate", "/api/judge", "/api/redteam", "/healthz")


@pytest.fixture(scope="module")
def model() -> readmodel.ReadModel:
    # One official run rather than both: the published intervals take about twenty seconds a
    # run to compute, and one is enough to hold every page to the report.
    return readmodel.build(ROOT, runs=[RUN])


@pytest.fixture(scope="module")
def client(model: readmodel.ReadModel) -> TestClient:
    return TestClient(service_app.create_app(ROOT, builder=lambda _root: model))


def test_every_page_and_api_answers(client: TestClient) -> None:
    for path in (*PAGES, *APIS):
        assert client.get(path).status_code == 200, path


def test_pages_are_plain_html_in_plain_punctuation(client: TestClient) -> None:
    for path in PAGES:
        body = client.get(path).text
        assert "<script" not in body, path
        assert not TYPOGRAPHIC.search(body), path
        assert 'name="viewport"' in body and "prefers-color-scheme: dark" in body


def test_the_service_only_reads(client: TestClient) -> None:
    for path in PAGES + APIS:
        assert client.post(path).status_code == 405, path


def test_the_drift_page_prints_the_readme_tables_numbers(
    client: TestClient, model: readmodel.ReadModel
) -> None:
    """Every cell of the README row the monthly job writes appears on the page, character for
    character, because both come from the same metrics and the same formatter."""
    body = client.get("/drift").text
    (run,) = model.runs
    rows = readme_rows(RUN, run.arms, {}).splitlines()[2:]
    assert len(rows) == 8
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        _, arm, accuracy, floor, _, refused, cost = cells
        for cell in (arm, accuracy, floor, refused, cost):
            assert cell in body, (arm, cell)


def test_duckdb_costs_match_what_the_run_recorded(model: readmodel.ReadModel) -> None:
    (run,) = model.runs
    (row,) = model.query("SELECT count(*) AS n, sum(cost_usd) AS usd FROM calls")
    assert row["n"] == run.meta.calls == 16800
    assert row["usd"] == pytest.approx(run.meta.spent_usd, abs=1e-6)
    per_arm = {
        r["arm_key"]: r["usd"]
        for r in model.query("SELECT arm_key, sum(cost_usd) AS usd FROM calls GROUP BY ALL")
    }
    for key, m in run.arms.items():
        assert per_arm[key] == pytest.approx(m.cost_usd, abs=1e-9), key


def test_the_read_model_never_loads_answer_text(model: readmodel.ReadModel) -> None:
    columns = {r["column_name"] for r in model.query("DESCRIBE calls")}
    assert "output" not in columns and "normalised" not in columns


def test_judge_figures_are_the_published_calibration(client: TestClient) -> None:
    judges = client.get("/api/judge").json()
    google = judges["google-judge-mid"]
    assert round(google["complete"]["kappa"]["point"], 3) == 0.914
    assert google["complete"]["usable"] is True
    assert round(google["faithful"]["kappa"]["point"], 3) == 0.108
    assert google["faithful"]["usable"] is False
    doc = (ROOT / "docs" / "judge-calibration-google-judge-mid.md").read_text(encoding="utf-8")
    assert "| Cohen's kappa | 0.914 (0.875 to 0.950) |" in doc


def test_red_team_figures_are_the_reports(client: TestClient) -> None:
    items = load_suite()
    answers = rt_run.read_answers(
        ROOT / "gate" / "redteam" / "runs" / "redteam-2026-09" / rt_run.ANSWERS_FILE
    )
    scored = rt_report.score(items, answers)
    got = client.get("/api/redteam").json()["runs"]["redteam-2026-09"]["arms"]
    for arm in scored.arms:
        for suite in SUITES:
            cell = scored.cells[(arm, suite)]
            assert got[arm][suite]["failed"] == cell.failed
            assert got[arm][suite]["failure_rate"]["point"] == pytest.approx(
                cell.rate.point, abs=1e-6
            )
    assert "60.0% (53.1 to 66.6)" in client.get("/redteam").text


def test_every_gate_decision_is_shown(client: TestClient, model: readmodel.ReadModel) -> None:
    body = client.get("/gate").text
    assert model.decisions
    for rec in model.decisions:
        assert rec.record_id in body
    assert json.loads(client.get("/api/gate").text)[0]["record_id"] == model.decisions[0].record_id


def test_rehearsals_are_not_part_of_the_record() -> None:
    runs = readmodel.official_runs(ROOT / "drift" / "runs")
    assert runs[:2] == ["2026-09", "2026-09-run2"]
    assert not [r for r in runs if "dry" in r]


def test_the_model_is_rebuilt_in_the_background_when_the_commit_moves(
    model: readmodel.ReadModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    commits = iter(["aaa", "bbb"])
    release = threading.Event()
    built: list[str] = []

    def builder(root: Path) -> readmodel.ReadModel:
        commit = next(commits)
        if built:
            release.wait(5)  # the rebuild is slow; the old model must keep serving meanwhile
        built.append(commit)
        m = readmodel.ReadModel(**{**model.__dict__, "commit": commit, "lock": threading.Lock()})
        return m

    monkeypatch.setattr(readmodel, "git_commit", lambda root: "bbb")
    holder = readmodel.Holder(ROOT, builder=builder, check_every=0.0)
    assert holder.current().commit == "aaa"  # starts the rebuild, answers with the old model
    assert holder.current().commit == "aaa"
    release.set()
    for _ in range(100):
        if holder.model.commit == "bbb":
            break
        threading.Event().wait(0.05)
    assert holder.current().commit == "bbb"
    assert built == ["aaa", "bbb"]


def test_nothing_in_drift_or_gate_imports_the_service() -> None:
    """The service depends on the library, never the other way: the monthly drift job and the
    gate on a pull request install without the service extra."""
    for package in ("drift", "gate"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if path.name == "cli.py" and package == "gate":
                    continue  # `gate serve` imports it lazily, inside the command
                assert not [n for n in names if n.split(".")[0] == "service"], path

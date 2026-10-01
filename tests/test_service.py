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
    # The A/A study is left out here, at most of a minute on its own, and held to its report by
    # the one test that needs it.
    return readmodel.build(ROOT, runs=[RUN], aa=False)


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
    assert round(google["complete"]["kappa"]["point"], 3) == 0.924
    assert google["complete"]["usable"] is True
    assert round(google["faithful"]["kappa"]["point"], 3) == 0.114
    assert google["faithful"]["usable"] is False
    doc = (ROOT / "docs" / "judge-calibration-google-judge-mid.md").read_text(encoding="utf-8")
    assert "| Cohen's kappa | 0.924 (0.886 to 0.958) |" in doc
    # The multi-part stratum is its own figure, on its own page section and data file, and the
    # published one above does not absorb it.
    mp = client.get("/data/judge-multipart.json").json()["google-judge-mid"]["complete"]
    assert round(mp["kappa"]["point"], 3) == 0.447 and mp["usable"] is False
    mp_doc = ROOT / "docs" / "judge-calibration-google-judge-mid-multipart.md"
    assert "| Cohen's kappa | 0.447 (0.218 to 0.642) |" in mp_doc.read_text(encoding="utf-8")
    assert "On the multi-part questions" in client.get("/judge").text
    # A kappa is not a share: printed as the report prints it, never as a percentage.
    page = client.get("/judge").text
    assert "0.924 (0.886 to 0.958)" in page and "92.4%" not in page


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


# ---------------------------------------------------------------------------- the static export


@pytest.fixture(scope="module")
def site(model: readmodel.ReadModel, tmp_path_factory: pytest.TempPathFactory) -> Path:
    from service.export import export

    out = tmp_path_factory.mktemp("site")
    export(model, out)
    return out


def test_every_exported_file_is_the_services_response_byte_for_byte(
    client: TestClient, site: Path
) -> None:
    """The published site is the service's output, so the service's guarantee (every figure is
    the report's) holds for what is actually published."""
    from service.app import ROUTES

    for route in ROUTES:
        got = client.get(route.path)
        assert got.status_code == 200, route.path
        assert (site / route.file).read_bytes() == got.content, route.path
        assert got.headers["content-type"].startswith(route.media_type.split(";")[0])
        for alias in route.aliases:  # gate serve still answers the old paths, identically
            assert client.get(alias).content == got.content, alias


def test_the_export_publishes_no_answer_text_and_nothing_withheld(site: Path) -> None:
    from drift.runner.records import read_records, records_path

    files = sorted(p for p in site.rglob("*") if p.is_file())
    assert not [p for p in files if "withheld" in p.as_posix()]
    # The fonts are binary and are the committed files themselves, checked below.
    files = [p for p in files if p.suffix != ".woff2"]
    published = "\n".join(p.read_text(encoding="utf-8") for p in files)
    answers = [
        r.output
        for r in read_records(records_path(ROOT / "drift" / "runs", RUN, "openweights-control"))
        if r.output and len(r.output) >= 60
    ]
    rt = rt_run.read_answers(
        ROOT / "gate" / "redteam" / "runs" / "redteam-2026-09" / rt_run.ANSWERS_FILE
    )
    answers += [a.text for a in rt if a.text and len(a.text) >= 60]
    assert len(answers) > 500
    assert not [a for a in answers if a in published]
    for key in ('"output"', '"text"', '"normalised"'):
        assert key not in published


def test_the_hosting_config_serves_every_page_at_its_clean_url(site: Path) -> None:
    from service.app import HTML, ROUTES
    from service.export import CONFIG_FILE, CSP

    cfg = json.loads((site / CONFIG_FILE).read_text(encoding="utf-8"))
    rewrites = {r["route"]: r["rewrite"] for r in cfg["routes"] if "rewrite" in r}
    for route in ROUTES:
        if route.media_type == HTML and route.path != "/":
            assert rewrites[route.path] == "/" + route.file
            assert (site / route.file).is_file()
    assert (site / "index.html").is_file()
    assert cfg["globalHeaders"]["Content-Security-Policy"] == CSP
    assert "script-src" not in CSP and "default-src 'none'" in CSP
    assert cfg["mimeTypes"][".json"] == "application/json"
    # The workflow's post-deploy check reads build.json, so it must never come from a cache, and
    # its rule must come before the /data/* one, since the first matching route wins.
    paths = [r["route"] for r in cfg["routes"]]
    assert paths.index("/data/build.json") < paths.index("/data/*")
    assert cfg["routes"][paths.index("/data/build.json")]["headers"] == {
        "Cache-Control": "no-store"
    }
    # Azure Static Web Apps reserves /api/ for Functions, so nothing is published under it.
    assert not (site / "api").exists()
    assert not [r for r in ROUTES if r.path.startswith("/api/")]


# ---------------------------------------------------------------------------- the front page


def test_the_fonts_are_the_committed_files_and_the_policy_allows_only_them(
    client: TestClient, site: Path
) -> None:
    """The portfolio's typefaces, served from this site and nowhere else: a font is an
    off-origin request like any other, and the policy would refuse one from another host."""
    from service.export import CSP

    static = ROOT / "service" / "static" / "fonts"
    for name in ("inter-latin.woff2", "newsreader-latin.woff2"):
        got = client.get(f"/fonts/{name}")
        assert got.headers["content-type"] == "font/woff2"
        assert got.content == (static / name).read_bytes() == (site / "fonts" / name).read_bytes()
    assert "font-src 'self'" in CSP
    for path in PAGES:
        body = client.get(path).text
        assert "url(/fonts/inter-latin.woff2)" in body
        # Nothing on a page loads from anywhere: links out are anchors, never sources.
        assert "src=" not in body and "@import" not in body, path
        assert body.count("url(") == 2, path


def test_the_front_page_figures_are_the_reports(model: readmodel.ReadModel) -> None:
    """The front page's hero and sections say what the reports say. The A/A figures are the
    committed A/A report's, computed by the same functions `gate aa` calls; the refusal check is
    the monthly report's own section."""
    from drift.analysis.report import classifier_check
    from service import pages

    runs = ["2026-09", "2026-09-run2"]
    study = readmodel.aa_study(ROOT, runs)
    assert study is not None
    m = readmodel.ReadModel(
        **{**model.__dict__, "aa": study, "aa_runs": tuple(runs), "lock": threading.Lock()}
    )
    body = pages.overview(m)
    assert not TYPOGRAPHIC.search(body)

    aa_report = (ROOT / "gate" / "reports" / "aa-2026-09.md").read_text(encoding="utf-8")
    fb, pr = study.false_block_rate(seed=0).compact(), study.point_rule_rate(seed=0).compact()
    assert f"| delta 3, as specified | all | {study.n} | 1.0 of 8 | {fb} | {pr} |" in aa_report
    assert fb in body and pr in body
    assert body.count('<span class="on"></span>') == sum(p.blocked for p in study.pairs) + sum(
        p.point_rule_blocked for p in study.pairs
    )

    check = classifier_check(RUN, ROOT / "drift")
    assert check is not None
    rate, _ = check
    report = (ROOT / "drift" / "reports" / f"{RUN}.md").read_text(encoding="utf-8")
    assert f"The classifier is wrong on **{rate.fmt()}**" in report
    assert rate.compact() in body

    (run,) = model.runs
    for arm in run.arms.values():
        assert arm.same_day_flip_rate.compact() in body
    assert "0.924 (0.886 to 0.958)" in body and "92.4%" not in body

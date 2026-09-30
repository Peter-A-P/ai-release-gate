"""The downstream adapter (PLAN.md B9): a side read from a file another project graded.

The fixtures are in the shape project 06's `smallprint gate export` writes: a spec with one
suite per extracted field, and a side per run with a verdict per filing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from gate import adapter, cli, ledger
from gate.spec import EvalSpec, load_spec

FIELDS = ("revenue", "net_income", "period_end")


def spec_dict(kind: str = "outcomes_file") -> dict[str, object]:
    return {
        "version": 1,
        "name": "fraction-of-the-bill",
        "delta_points": 3.0,
        "alpha": 0.05,
        "resamples": 2000,
        "seed": 0,
        "suites": [{"key": f, "source": {"kind": kind, "block": f}} for f in FIELDS],
    }


def side_dict(wrong_every: int, *, n: int = 400, label: str = "m") -> dict[str, object]:
    suites = {}
    for f in FIELDS:
        suites[f] = {
            "suite": f,
            "outcomes": {f"test-{i}": i % wrong_every != 0 for i in range(n)},
            "ungradeable_items": 2,
            "calls": n + 2,
            "latency_p50_ms": 640.0,
            "cost_usd": 0.4,
            "uncosted_calls": 0,
        }
    return {
        "label": label,
        "source": {"run_id": f"run-{label}", "directory": "runs/x"},
        "suites": suites,
    }


def write(tmp: Path, name: str, data: object) -> Path:
    path = tmp / name
    text = yaml.safe_dump(data) if name.endswith(".yaml") else json.dumps(data, indent=2)
    path.write_text(text, encoding="utf-8")
    return path


def spec() -> EvalSpec:
    return EvalSpec.model_validate(spec_dict())


def test_a_side_file_becomes_a_side_named_by_the_hash_of_its_bytes(tmp_path: Path) -> None:
    path = write(tmp_path, "candidate.json", side_dict(50, label="selfhosted/2b"))
    side = adapter.load_side(path, spec())
    assert side.label == "selfhosted/2b"
    assert set(side.suites) == set(FIELDS)
    s = side.suites["revenue"]
    assert s.items == 400 and s.ungradeable_items == 2 and s.calls == 402
    assert side.source["kind"] == "outcomes_file" and side.source["run_id"] == "run-selfhosted/2b"
    import hashlib

    assert side.source["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["suites"].pop("revenue"), "no suite for"),
        (lambda d: d["suites"]["revenue"].update(suite="income"), "calls itself"),
        (lambda d: d["suites"]["revenue"]["outcomes"].update({"test-0": 1}), "not a side file"),
        (lambda d: d["suites"]["revenue"]["outcomes"].update({"test-0": "yes"}), "not a side file"),
        (lambda d: d.update(extra=1), "not a side file"),
        (lambda d: d["suites"]["revenue"].update(uncosted_calls=999), "more uncosted"),
        (lambda d: d["source"].update(file_sha256="x"), "gate's to write"),
    ],
)
def test_a_file_read_loosely_is_refused_not_guessed_at(
    tmp_path: Path, mutate: object, message: str
) -> None:
    data = side_dict(50)
    mutate(data)  # type: ignore[operator]
    with pytest.raises(adapter.AdapterError, match=message):
        adapter.load_side(write(tmp_path, "s.json", data), spec())


def test_a_spec_that_mixes_a_file_with_the_drift_record_is_refused(tmp_path: Path) -> None:
    mixed = spec_dict()
    mixed["suites"].append({"key": "gsm", "source": {"kind": "drift_block", "block": "b"}})  # type: ignore[attr-defined]
    with pytest.raises(adapter.AdapterError, match="mixes source kinds"):
        adapter.load_side(write(tmp_path, "s.json", side_dict(50)), EvalSpec.model_validate(mixed))


def test_an_outcomes_file_suite_names_its_block_and_takes_no_grader() -> None:
    bare = spec_dict()
    bare["suites"] = [{"key": "revenue", "source": {"kind": "outcomes_file"}}]
    with pytest.raises(ValueError, match="names its block"):
        EvalSpec.model_validate(bare)
    judged = spec_dict()
    judged["suites"] = [
        {
            "key": "revenue",
            "source": {"kind": "outcomes_file", "block": "revenue"},
            "grader": {"judge": "google-judge-mid", "task": "complete"},
        }
    ]
    with pytest.raises(ValueError, match="already graded"):
        EvalSpec.model_validate(judged)


def test_the_shipped_specs_keep_their_hashes() -> None:
    """Adding a source kind must not move any existing spec's hash: ledger records are
    content-addressed on it."""
    assert load_spec(cli.DEFAULT_SPEC).sha256().startswith("1b6d78c7491ba911")


def test_compare_decides_on_the_files_and_writes_to_the_projects_own_ledger(
    tmp_path: Path,
) -> None:
    sp = write(tmp_path, "spec.yaml", spec_dict())
    base = write(tmp_path, "baseline.json", side_dict(50, label="frontier"))
    same = write(tmp_path, "same.json", side_dict(50, label="fine-tune"))
    worse = write(tmp_path, "worse.json", side_dict(5, label="fine-tune-q4"))
    theirs = tmp_path / "their" / "ledger.jsonl"
    runner = CliRunner()
    args = ["compare", "--spec", str(sp), "--baseline", str(base), "--ledger", str(theirs)]
    ok = runner.invoke(cli.app, [*args, "--candidate", str(same)])
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(cli.app, [*args, "--candidate", str(worse)])
    assert bad.exit_code == 1, bad.output
    assert "cannot rule out a 3% drop" in bad.output
    first, second = list(ledger.read(theirs))
    assert first.passed and not second.passed
    assert second.candidate["kind"] == "outcomes_file"
    assert second.candidate["file_sha256"] and second.baseline["label"] == "frontier"
    assert {s.suite for s in second.suites} == set(FIELDS)


def test_a_file_spec_refuses_a_drift_arm(tmp_path: Path) -> None:
    sp = write(tmp_path, "spec.yaml", spec_dict())
    out = CliRunner().invoke(cli.app, ["run", "2026-09/anthropic-alias", "--spec", str(sp)])
    assert out.exit_code == 2
    assert "not read from the drift record" in out.output

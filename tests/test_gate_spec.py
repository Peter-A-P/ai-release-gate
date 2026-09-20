"""The eval spec: loads, validates, hashes, and the shipped one is sound."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gate.spec import EvalSpec, Source, SuiteSpec, load_spec

SHIPPED = Path(__file__).resolve().parent.parent / "gate" / "specs" / "drift-blocks.yaml"


def test_the_shipped_spec_loads_and_names_every_block_once() -> None:
    s = load_spec(SHIPPED)
    assert s.name == "drift-blocks" and s.delta_points == 3.0
    keys = [su.key for su in s.suites]
    assert len(keys) == len(set(keys)) == 8
    assert {su.source.block for su in s.suites} == {
        "closed_form_reasoning",
        "multiple_choice",
        "instruction_following",
        "structured_extraction",
        "refusal_calibration",
        "long_context_recall",
        "paraphrase_robustness",
    }
    assert sum(1 for su in s.suites if su.source.held_out) == 1
    assert not any(su.correct_for_dependence for su in s.suites), (
        "the correction is shown, not used, until the A/A study earns it"
    )


def test_the_hash_is_over_content_not_layout(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(
        "version: 1\nname: x\nsuites:\n  - key: s\n    source: {block: b}\n", encoding="utf-8"
    )
    b.write_text(
        "# a comment\nsuites:\n- source:\n    block: b\n  key: s\nname: x\nversion: 1\n",
        encoding="utf-8",
    )
    assert load_spec(a).sha256() == load_spec(b).sha256()
    c = tmp_path / "c.yaml"
    c.write_text(
        "version: 1\nname: x\ndelta_points: 5\nsuites:\n  - key: s\n    source: {block: b}\n",
        encoding="utf-8",
    )
    assert load_spec(c).sha256() != load_spec(a).sha256()


def test_duplicate_keys_and_unknown_fields_are_refused() -> None:
    s = SuiteSpec(key="s", source=Source(block="b"))
    with pytest.raises(ValidationError, match="appears twice"):
        EvalSpec(version=1, name="x", suites=(s, s))
    with pytest.raises(ValidationError):
        EvalSpec.model_validate(
            {
                "version": 1,
                "name": "x",
                "suites": [{"key": "s", "source": {"block": "b"}}],
                "tolerance": 3,
            }
        )
    with pytest.raises(ValidationError):
        SuiteSpec(key="Bad Key", source=Source(block="b"))


def test_delta_per_suite_and_the_study_variants() -> None:
    s = EvalSpec(
        version=1,
        name="x",
        delta_points=3.0,
        suites=(
            SuiteSpec(key="a", source=Source(block="a"), delta_points=5.0),
            SuiteSpec(key="b", source=Source(block="b")),
        ),
    )
    assert s.delta_for(s.suite("a")) == 0.05 and s.delta_for(s.suite("b")) == 0.03
    at_two = s.with_delta(2.0)
    assert all(at_two.delta_for(su) == 0.02 for su in at_two.suites), "overrides cleared"
    every = s.deciding_every_suite()
    assert all(su.min_items == 1 for su in every.suites)
    assert s.suite("a").min_items is None, "the original is untouched"
    assert every.sha256() != s.sha256()

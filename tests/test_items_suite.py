"""Items validate, the suite hashes deterministically, freeze and verify work."""

from __future__ import annotations

from pathlib import Path

import pytest

from drift.graders import GRADERS
from drift.items import Item, check_item, validate_file, write_items
from drift.panel import Panel, load_panel
from drift.suite import Suite, freeze, heldout_hashes, load_suite, suite_hash, verify

from .conftest import make_items


def test_canonical_is_order_independent() -> None:
    a = make_items()
    b = list(reversed(a))
    assert suite_hash(a) == suite_hash(b)
    assert a[0].sha256() == Item.model_validate(a[0].model_dump()).sha256()


def test_check_item_rules() -> None:
    it = make_items()[0]
    assert check_item(it, grader_names=GRADERS) == []
    em_dash = chr(0x2014)
    bad = it.model_copy(update={"prompt": f"What is 1 {em_dash} 2?", "grader": "judge"})
    problems = check_item(bad, grader_names=GRADERS)
    assert any("typographic" in p for p in problems) and any(
        "unknown grader" in p for p in problems
    )
    wrong_prefix = it.model_copy(update={"id": "choice-0001"})
    assert any("should start with" in p for p in check_item(wrong_prefix, grader_names=GRADERS))
    held = it.model_copy(update={"held_out": True})
    assert any("held out" in p for p in check_item(held, grader_names=GRADERS))


def test_validate_file_reports_duplicates_and_schema_errors(tmp_path: Path) -> None:
    items = make_items()[:2]
    p = tmp_path / "x.jsonl"
    write_items(p, [items[0], items[0], items[1]])
    problems = validate_file(p, grader_names=GRADERS)
    assert problems == ["reason-0000: duplicate id"]
    p.write_text('{"id": "reason-0001"}\n', encoding="utf-8")
    assert (
        validate_file(p, grader_names=GRADERS)
        and "x.jsonl:1" in validate_file(p, grader_names=GRADERS)[0]
    )


def test_freeze_verify_and_heldout(suite_root: Path, suite: Suite, tmp_path: Path) -> None:
    held = [
        it.model_copy(
            update={
                "id": f"extract-{i:04d}",
                "block": "structured_extraction",
                "held_out": True,
                "grader": "json_schema_exact",
                "expected": {"schema": {"type": "object"}, "values": {"a": 1}},
            }
        )
        for i, it in enumerate(make_items()[:3])
    ]
    heldout_file = tmp_path / "heldout-extract.jsonl"
    write_items(heldout_file, held)
    h, n = freeze(suite_root, heldout_file=heldout_file)
    assert h == suite.hash and n == 3
    assert verify(suite_root)
    assert heldout_hashes(suite_root) == {it.sha256() for it in held}
    # Editing a frozen file is detected.
    f = suite_root / "v1" / "closed_form_reasoning.jsonl"  # the file that contains "plus"
    f.write_text(f.read_text(encoding="utf-8").replace("plus", "minus", 1), encoding="utf-8")
    assert not verify(suite_root)


def test_duplicate_ids_across_files_refused(suite_root: Path) -> None:
    items = make_items()[:1]
    write_items(suite_root / "v1" / "dup.jsonl", items)
    with pytest.raises(ValueError, match="duplicate item id"):
        load_suite(suite_root)


def test_repo_panel_loads_but_is_not_ready() -> None:
    panel = load_panel(Path(__file__).resolve().parent.parent / "drift" / "panel.yaml")
    assert isinstance(panel, Panel) and not panel.ready
    assert panel.control() is not None and len(panel.arms) == 8
    assert panel.providers == ["anthropic", "openai", "google", "openweights"]
    assert sum(1 for a in panel.arms if a.provider == "anthropic") == 3


def test_panel_arm_keys_must_start_with_the_provider() -> None:
    import datetime as dt

    from drift.panel import Arm

    with pytest.raises(ValueError, match="start with their provider"):
        Panel(
            version=1,
            chosen=dt.date(2026, 9, 27),
            arms=[Arm(key="control", provider="openweights", model="x", arm="control", family="c")],
        )


def test_public_suite_files_may_not_hold_heldout_items(suite_root: Path) -> None:
    held = make_items()[0].model_copy(
        update={"id": "extract-0001", "block": "structured_extraction", "held_out": True}
    )
    write_items(suite_root / "v1" / "extra.jsonl", [held])
    with pytest.raises(ValueError, match="must not be in the public suite"):
        load_suite(suite_root)


def test_load_heldout_from_environment(suite_root: Path, tmp_path: Path) -> None:
    from drift.suite import HeldoutError, load_heldout

    # Nothing committed yet: nothing to load, no error.
    assert load_heldout(suite_root, env={}) == []
    held = [
        make_items()[0].model_copy(
            update={
                "id": f"extract-{i:04d}",
                "block": "structured_extraction",
                "held_out": True,
                "grader": "json_schema_exact",
                "expected": {"schema": {"type": "object"}, "values": {"a": 1}},
            }
        )
        for i in range(2)
    ]
    heldout_file = tmp_path / "heldout-extract.jsonl"
    write_items(heldout_file, held)
    freeze(suite_root, heldout_file=heldout_file)
    # Committed but no source: an official run must not silently skip them.
    with pytest.raises(HeldoutError, match="neither DRIFT_HELDOUT_FILE nor DRIFT_HELDOUT_ITEMS"):
        load_heldout(suite_root, env={})
    # From a file path, and from the text of an Actions secret.
    assert load_heldout(suite_root, env={"DRIFT_HELDOUT_FILE": str(heldout_file)}) == held
    text = heldout_file.read_text(encoding="utf-8")
    assert load_heldout(suite_root, env={"DRIFT_HELDOUT_ITEMS": text}) == held
    # A changed item, or a missing one, is refused.
    changed = text.replace("plus", "minus", 1)
    with pytest.raises(HeldoutError, match="does not match any committed hash"):
        load_heldout(suite_root, text=changed)
    with pytest.raises(HeldoutError, match="have no item"):
        load_heldout(suite_root, text=text.splitlines()[0] + "\n")
    with pytest.raises(HeldoutError, match="not marked held_out"):
        load_heldout(suite_root, text=text.replace('"held_out":true', '"held_out":false'))


def test_cli_panel_providers_and_collect_of_an_empty_month() -> None:
    from typer.testing import CliRunner

    from drift.cli import app

    r = CliRunner().invoke(app, ["panel", "providers", "--json"])
    assert (
        r.exit_code == 0 and r.output.strip() == '["anthropic", "openai", "google", "openweights"]'
    )
    r = CliRunner().invoke(app, ["collect", "--month", "1999-01", "--no-readme"])
    assert r.exit_code == 1 and "no arm has recorded" in r.output


def test_verify_before_freeze_is_a_clear_refusal(suite_root: Path) -> None:
    from drift.suite import NotFrozenError

    with pytest.raises(NotFrozenError, match="not frozen"):
        verify(suite_root)


def test_repo_system_prompts_document_exists() -> None:
    assert (
        Path(__file__).resolve().parent.parent / "drift" / "suite" / "v1" / "SYSTEM.md"
    ).is_file()


def test_parse_model_list_handles_each_vendor_shape() -> None:
    from drift.panel import parse_model_list

    openai_like = {"data": [{"id": "gpt-x-2026-01-01"}, {"id": "gpt-x"}]}
    assert parse_model_list("openai", openai_like) == ["gpt-x", "gpt-x-2026-01-01"]
    anthropic_like = {"data": [{"id": "claude-haiku-4-5-20251001"}]}
    assert parse_model_list("anthropic", anthropic_like) == ["claude-haiku-4-5-20251001"]
    google_like = {"models": [{"name": "models/gemini-2.5-flash"}, {"name": "models/gemini-x"}]}
    assert parse_model_list("google", google_like) == ["gemini-2.5-flash", "gemini-x"]
    together_like = [{"id": "org/Model-70B"}, {"id": "org/Other"}]
    assert parse_model_list("openweights", together_like) == ["org/Model-70B", "org/Other"]
    assert parse_model_list("openai", None) == []


def test_snapshot_alias_pairs() -> None:
    from drift.panel import snapshot_alias_pairs

    ids = [
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "gpt-x",
        "gpt-x-2026-01-01",
        "orphan-20250101",
    ]
    assert snapshot_alias_pairs(sorted(ids)) == [
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5"),
        ("gpt-x-2026-01-01", "gpt-x"),
    ]
    # A vendor whose identifiers are all undated has no pair to compare.
    assert snapshot_alias_pairs(["claude-sonnet-5", "claude-opus-5"]) == []


def test_example_items_validate() -> None:
    """The worked examples shipped for the writing session pass every check."""
    from drift.graders import GRADERS, grader
    from drift.items import read_items, validate_file

    examples = Path(__file__).resolve().parent.parent / "docs" / "examples"
    files = sorted(examples.glob("*.jsonl"))
    assert len(files) == 3
    for f in files:
        assert validate_file(f, grader_names=GRADERS) == []
        for item in read_items(f):
            assert grader(item.grader).check_expected(item.expected) == []

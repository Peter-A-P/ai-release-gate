"""The review of the draft multi-part questions: one keypress each, resumable, nothing lost."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

import gate.cli as cli
from gate import draft_review as dr
from gate import gold

GOLD = Path(__file__).resolve().parent.parent / "gate" / "gold"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in (gold.SOURCES_FILE, gold.QUESTIONS_FILE, gold.INSTANCES_FILE):
        shutil.copy(GOLD / name, tmp_path / name)
    monkeypatch.setattr(cli, "GOLD", tmp_path)
    monkeypatch.setenv("COLUMNS", "120")
    return tmp_path


def drive(monkeypatch: pytest.MonkeyPatch, keys: list[str], *args: str, typed: str = "") -> str:
    presses = iter(keys)
    monkeypatch.setattr(click, "getchar", lambda: next(presses))
    result = CliRunner().invoke(cli.app, ["gold", "review-draft", *args], input=typed)
    assert result.exit_code == 0, result.output
    return result.output


def decisions(root: Path) -> list[tuple[str, str, str]]:
    rows = [json.loads(x) for x in (root / dr.REVIEW_FILE).read_text(encoding="utf-8").splitlines()]
    return [(r["key"], r["decision"], r["note"]) for r in rows]


def test_the_fifty_and_the_spares_are_told_apart() -> None:
    fifty, spares = dr.drafts()
    assert len(fifty) == 50 and len(spares) == 21
    assert all(d.qid for d in fifty) and not any(s.qid for s in spares)
    assert len({d.key for d in [*fifty, *spares]}) == 71


def test_one_key_each_and_a_change_is_typed_once(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifty, _ = dr.drafts()
    drive(monkeypatch, ["y", "n", "c", "q"], typed="ask only about the fees\n")
    assert decisions(root) == [
        (fifty[0].key, "keep", ""),
        (fifty[1].key, "drop", ""),
        (fifty[2].key, "change", "ask only about the fees"),
    ]


def test_it_resumes_at_the_first_question_not_yet_reviewed(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive(monkeypatch, ["y", "y", "q"])
    out = drive(monkeypatch, ["q"])
    assert "2 of 50 reviewed" in out and "[3/50]  q-203" in out


def test_back_corrects_a_slip_and_the_last_decision_wins(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifty, _ = dr.drafts()
    out = drive(monkeypatch, ["n", "b", "y", "q"])
    assert "you said: drop" in out, "going back shows what was said, so a fix is not from memory"
    assert [d for _, d, _ in decisions(root)] == ["drop", "keep"], "nothing is erased"
    assert dr.latest(dr.read_reviews(root / dr.REVIEW_FILE))[fifty[0].key].decision == "keep"


def test_a_stray_key_asks_again_and_p_shows_the_whole_page(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = drive(monkeypatch, ["x", "p", "y", "q"])
    assert "not one of those keys" in out
    assert "PAGE" in out and "Financial institutions must make the first $100" in out
    assert len(decisions(root)) == 1


def test_a_page_that_lost_a_question_is_offered_its_spare(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, spares = dr.drafts()
    # Drop the first (fcac-020), keep the other 49, then take the spare offered.
    out = drive(monkeypatch, ["n", *["y"] * 49, "y"])
    spare = next(s for s in spares if s.source_id == "fcac-020")
    assert "1 spares are on pages that lost a question" in out
    assert decisions(root)[-1] == (spare.key, "promote", "")
    assert "review done: 49 kept, 0 to change, 1 dropped, 1 spares brought in" in out


def test_a_question_whose_points_alone_were_edited_comes_back_too() -> None:
    fifty, spares = dr.drafts()
    d = fifty[0]
    old = dr.DraftReview(
        key=dr.question_key(d.source_id, d.question, d.must_mention[:-1]),
        source_id=d.source_id,
        question=d.question,
        decision="change",
        note="drop the last point",
        reviewed_utc="2026-09-29T00:00:00Z",
    )
    assert dr.tally(fifty, spares, dr.latest([old])).reviewed == 0


def test_an_edited_question_comes_back_to_the_queue() -> None:
    fifty, spares = dr.drafts()
    stale = dr.DraftReview(
        key=dr.question_key(
            fifty[0].source_id, fifty[0].question + " (edited)", fifty[0].must_mention
        ),
        source_id=fifty[0].source_id,
        question=fifty[0].question + " (edited)",
        decision="keep",
        reviewed_utc="2026-09-29T00:00:00Z",
    )
    assert dr.tally(fifty, spares, dr.latest([stale])).reviewed == 0


def test_each_point_is_shown_in_the_fullest_sentence_holding_it() -> None:
    g = gold.load(GOLD)
    before, hit, _ = dr.context(g.by_source["fcac-020"], "first $100")
    assert hit == "first $100"
    assert "Financial institutions must make the" in before, "not the bare heading"
    for d in dr.drafts()[0]:
        for point in d.must_mention:
            _, hit, _ = dr.context(g.by_source[d.source_id], point)
            phrase = gold.point_parts(point)[1]
            assert " ".join(hit.split()).casefold() == " ".join(phrase.split()).casefold()

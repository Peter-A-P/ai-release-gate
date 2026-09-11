"""The long-context generator: Gutenberg text handling, the seeded window and planting, the
items, the manifest and the audit path. Offline: the tests build a fake book in memory."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from drift.graders import GRADERS, grader
from drift.items import SYSTEM_PROMPTS, check_item, read_items
from drift.sampling.fetch import Fetched
from drift.sampling.longcontext import (
    BOOKS,
    FACTS,
    MAX_DEPTH,
    MIN_DEPTH,
    Book,
    Fact,
    Generated,
    GenerationError,
    body_text,
    cut,
    differences,
    fact_assignment,
    generate,
    items_for,
    manifest,
    paragraphs,
    suite_file,
    write,
)
from drift.sampling.sample import SUITE_HASH_FILE, SamplingError, rng_for
from drift.suite import load_suite

BOOK = Book(1, "A Fake Book", "Nobody")
# Built from the code point so the test source itself stays plain (repository rule).
CURLY = chr(0x2019)


def fake_gutenberg(n_paragraphs: int = 400, words_per_paragraph: int = 30) -> bytes:
    """A file in the shape Gutenberg serves: boilerplate, START marker, hard-wrapped
    paragraphs separated by blank lines, END marker, more boilerplate. CRLF line endings and
    a curly apostrophe, both of which the generator must map away."""
    rng = random.Random(1)
    vocab = [
        "the",
        "of",
        "and",
        "a",
        "to",
        "in",
        "it",
        "was",
        "he",
        "that",
        "she",
        "his",
        "her",
        "with",
        "for",
        "as",
        "had",
        "at",
        "on",
        "by",
    ]
    paras = []
    for i in range(n_paragraphs):
        words = [rng.choice(vocab) for _ in range(words_per_paragraph)]
        words[0] = f"Para{i}"
        words[5] = "don" + CURLY + "t"
        line1, line2 = " ".join(words[:15]), " ".join(words[15:])
        paras.append(f"{line1}\r\n{line2}")
    text = (
        "The Project Gutenberg eBook of A Fake Book\r\nTitle: A Fake Book\r\n\r\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK A FAKE BOOK ***\r\n\r\n"
        + "\r\n\r\n".join(paras)
        + "\r\n\r\n*** END OF THE PROJECT GUTENBERG EBOOK A FAKE BOOK ***\r\n"
        "licence text\r\n"
    )
    return text.encode("utf-8")


def fake_loaded(raw: bytes) -> tuple[list[str], Fetched]:
    paras = paragraphs(body_text(raw))
    return paras, Fetched(
        name="gutenberg:1",
        url=BOOK.url,
        sha256="0" * 64,
        fetched="2026-09-11",
        rows_total=len(paras),
    )


def test_body_text_strips_the_boilerplate_and_maps_punctuation() -> None:
    text = body_text(fake_gutenberg(20))
    assert "Project Gutenberg eBook of" not in text
    assert "licence text" not in text
    assert CURLY not in text and "don't" in text
    assert "\r" not in text


def test_body_text_refuses_a_file_without_markers_or_marked_copyrighted() -> None:
    with pytest.raises(GenerationError, match="markers not found"):
        body_text(b"just some text without the markers")
    raw = fake_gutenberg(20).replace(
        b"Title: A Fake Book", b"*** This is a COPYRIGHTED Project Gutenberg eBook. ***"
    )
    with pytest.raises(GenerationError, match="copyrighted"):
        body_text(raw)


def test_paragraphs_join_hard_wrapped_lines() -> None:
    paras = paragraphs(body_text(fake_gutenberg(5)))
    assert len(paras) == 5
    assert all("\n" not in p for p in paras)
    assert paras[0].startswith("Para0 ") and len(paras[0].split()) == 30


def test_cut_is_seeded_sized_and_plants_the_fact_inside_the_depth_range() -> None:
    paras, _ = fake_loaded(fake_gutenberg())
    fact = FACTS[0]
    a = cut(BOOK, paras, fact, rng_for(1, "x"), target_words=600)
    b = cut(BOOK, paras, fact, rng_for(1, "x"), target_words=600)
    c = cut(BOOK, paras, fact, rng_for(2, "x"), target_words=600)
    assert (a.start, a.end, a.plant_at) == (b.start, b.end, b.plant_at)
    assert (a.start, a.plant_at) != (c.start, c.plant_at)
    assert a.words >= 600
    assert MIN_DEPTH <= a.depth <= MAX_DEPTH
    assert a.body[a.plant_at] == fact.sentence
    assert a.prompt.startswith("Passage:\n\n") and a.prompt.endswith("Question: " + fact.question)
    # The window is cut from the body, not the front or back matter.
    assert a.start >= int(len(paras) * 0.10) and a.end <= int(len(paras) * 0.95)


def test_cut_refuses_a_window_that_already_contains_the_answer() -> None:
    paras, _ = fake_loaded(fake_gutenberg())
    everywhere = Fact("x", "The word was the.", "What was the word?", "the")
    with pytest.raises(GenerationError, match="answer_in_passage"):
        cut(BOOK, paras, everywhere, rng_for(1, "x"), target_words=600)


def test_cut_refuses_a_text_too_short_for_the_window() -> None:
    paras, _ = fake_loaded(fake_gutenberg(40))
    with pytest.raises(GenerationError, match="past_the_end"):
        cut(BOOK, paras, FACTS[0], rng_for(1, "x"), target_words=5000)


def test_fact_assignment_is_a_seeded_permutation_with_no_repeats() -> None:
    a = fact_assignment(20260927, 20)
    assert len({f.key for f in a}) == 20
    assert a != list(FACTS[:20]) or len(FACTS) == 20
    assert a == fact_assignment(20260927, 20)
    assert a != fact_assignment(1, 20)
    with pytest.raises(GenerationError, match="only"):
        fact_assignment(1, len(FACTS) + 1)


def test_each_fact_answer_passes_its_own_grader_and_is_plain() -> None:
    from drift.items import TYPOGRAPHIC

    for f in FACTS:
        assert grader("exact").grade(f.answer, {"answer": f.answer}).correct
        assert grader("exact").grade(f.answer + ".", {"answer": f.answer}).correct
        for text in (f.sentence, f.question, f.answer):
            assert not TYPOGRAPHIC.search(text)
        assert f.answer in f.sentence
        assert f.answer.casefold() not in f.question.casefold()
    assert len({f.key for f in FACTS}) == len(FACTS) == len({f.answer for f in FACTS})


def test_books_are_twenty_distinct_ids() -> None:
    assert len(BOOKS) == 20
    assert len({b.gutenberg_id for b in BOOKS}) == 20
    assert all(b.url.endswith(f"/pg{b.gutenberg_id}.txt") for b in BOOKS)


def _generated(n_books: int = 3, seed: int = 7) -> tuple[list[Book], list[Generated]]:
    books = [Book(i + 1, f"Book {i + 1}", "Nobody") for i in range(n_books)]
    loaded = [fake_loaded(fake_gutenberg()) for _ in books]
    return books, generate(books, loaded, seed=seed, target_words=600)


def test_generate_gives_one_passage_per_book_and_adding_a_book_moves_nothing() -> None:
    books, two = _generated(2)
    _, three = _generated(3)
    assert [g.passage.book for g in two] == books
    for g2, g3 in zip(two, three, strict=False):
        assert (g2.passage.start, g2.passage.plant_at) == (g3.passage.start, g3.passage.plant_at)


def test_items_carry_the_block_system_prompt_ids_from_1001_and_pass_validation() -> None:
    _, generated = _generated(3)
    items = items_for(generated, seed=7, generated_on="2026-09-11")
    assert [it.id for it in items] == ["recall-1001", "recall-1002", "recall-1003"]
    for it, g in zip(items, generated, strict=True):
        assert it.block == "long_context_recall"
        assert it.system == SYSTEM_PROMPTS["long_context_recall"]
        assert it.grader == "exact" and it.expected == {"answer": g.passage.fact.answer}
        assert check_item(it, grader_names=GRADERS) == []
        assert "seed 7" in it.source and "depth" in it.source
        assert len(it.prompt.split()) > 300  # the long-context block is exempt from the limit


def test_manifest_records_the_seed_the_window_the_depth_and_the_bytes() -> None:
    _, generated = _generated(2)
    items = items_for(generated, seed=7, generated_on="2026-09-11")
    record = manifest(generated, items, seed=7, generated_on="2026-09-11", target_words=600)
    assert record["seed"] == 7 and record["items_total"] == 2 and record["target_words"] == 600
    entry = record["items"][0]
    assert entry["id"] == "recall-1001"
    assert entry["fetch"]["payload_sha256"] == "0" * 64
    assert entry["window"] == [generated[0].passage.start, generated[0].passage.end - 1]
    assert entry["words"] >= 600
    assert MIN_DEPTH <= entry["depth"] <= MAX_DEPTH
    assert entry["fact"] == generated[0].passage.fact.key


def test_write_then_differences_is_the_audit_path(tmp_path: Path) -> None:
    _, generated = _generated(2)
    items = items_for(generated, seed=7, generated_on="2026-09-11")
    path = write(tmp_path, generated, items, seed=7, generated_on="2026-09-11")
    assert path.name == "LONGCONTEXT.json"
    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 7
    written = suite_file(tmp_path)
    assert [it.id for it in read_items(written)] == ["recall-1001", "recall-1002"]
    assert len(load_suite(tmp_path).items) == 2
    assert differences(tmp_path, items) == []
    # A regeneration on another day differs only in `source`, which is not compared.
    later = items_for(generated, seed=7, generated_on="2026-09-12")
    assert differences(tmp_path, later) == []
    # A changed passage is reported.
    lines = written.read_text(encoding="utf-8").splitlines()
    written.write_text(
        lines[0].replace("Question:", "Query:") + "\n" + lines[1] + "\n", encoding="utf-8"
    )
    problems = differences(tmp_path, items)
    assert problems and "2 items on disk, 2 generated, 1 identical" in problems[0]
    assert differences(tmp_path / "elsewhere", items) == [
        "long_context_recall-gutenberg.jsonl: missing"
    ]


def test_write_refuses_a_frozen_suite(tmp_path: Path) -> None:
    (tmp_path / "v1").mkdir(parents=True)
    (tmp_path / "v1" / SUITE_HASH_FILE).write_text("deadbeef\n", encoding="utf-8")
    _, generated = _generated(1)
    items = items_for(generated, seed=7, generated_on="2026-09-11")
    with pytest.raises(SamplingError, match="frozen"):
        write(tmp_path, generated, items, seed=7, generated_on="2026-09-11")

"""Long-context recall: public-domain passages with one planted fact, generated from a seed.

PLAN.md section 3: twenty items, each an 8k-token passage with one planted fact and a question
at the end, graded by exact match. Nothing here is hand-written. The passages are windows of
Project Gutenberg texts (public domain in the United States, the Gutenberg boilerplate
removed), the facts are invented sentences whose answer is a name or a number that appears
nowhere else in the passage, and where each fact is planted is chosen from the seed.

Like the sampler, this is a development tool that runs once before the freeze. The record of
the generation is `drift/suite/v1/LONGCONTEXT.json`: the seed, the bytes each passage was cut
from, the paragraph window, its word count, and the depth of the planted fact. After the
freeze `drift longcontext --check` regenerates into memory and reports any file that differs.

Why invented facts: every model on the panel has read these novels. A question about the
book itself would measure memory of the training set, not recall from the context. A
question about a sentence that exists only in this passage cannot be answered from memory.

Why the depth is recorded: recall degrades with where the fact sits in a long passage, so a
month-over-month change on this block can be read against the depth of each item.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drift.graders import GRADERS, grader
from drift.graders.normalise import collapse
from drift.items import BLOCK_PREFIX, SYSTEM_PROMPTS, Item, check_item, read_items, write_items
from drift.sampling.fetch import Fetched, FetchError, fetch, is_cached
from drift.sampling.sample import (
    SAMPLED_ID_START,
    SamplingError,
    is_frozen,
    rng_for,
)
from drift.sampling.sources import TOKENS_PER_WORD, plain, screen

GENERATOR_VERSION = 1
BLOCK = "long_context_recall"
GRADER = "exact"
MANIFEST_FILE = "LONGCONTEXT.json"
SUITE_FILE = f"{BLOCK}-gutenberg.jsonl"
GUTENBERG_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
PAUSE_S = 1.0  # between uncached fetches; Gutenberg asks for politeness from scripts
LICENCE = "Public domain (United States); Project Gutenberg boilerplate removed"

# The plan says 8k tokens. There is no tokenizer here, so the passage is sized in words at
# the same conservative ratio the instruction-following ceiling uses: 8,000 / 1.4 = 5,714.
TARGET_TOKENS = 8000
TARGET_WORDS = int(TARGET_TOKENS / TOKENS_PER_WORD)
# The fact is planted at a paragraph boundary whose depth (share of the passage's words before
# it) lies in this range: never the very start or end, where recall is trivially easy.
MIN_DEPTH, MAX_DEPTH = 0.10, 0.90
# Windows start after the first tenth of a book's paragraphs (title page, contents, preface)
# and end before the last twentieth (transcriber's notes, indexes).
FRONT_MATTER, BACK_MATTER = 0.10, 0.05
MIN_WINDOW_PARAGRAPHS = 8
ATTEMPTS = 200

_START = re.compile(r"^\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.MULTILINE)
_END = re.compile(r"^\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.MULTILINE)
# Gutenberg distributes some copyrighted texts (mostly modern translations) with permission
# and says so in the header. Those are not public domain and cannot be published here.
_COPYRIGHTED = re.compile(r"COPYRIGHTED Project Gutenberg eBook", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Book:
    gutenberg_id: int
    title: str
    author: str

    @property
    def url(self) -> str:
        return GUTENBERG_URL.format(id=self.gutenberg_id)


# Twenty novels of ordinary English prose, one passage from each, so no author's style
# dominates the block. All were written in English and published before 1930, so the text is
# public domain in the United States. Translations are avoided because a modern translation
# on Gutenberg can be copyrighted: Wyllie's Metamorphosis is, and was dropped for that reason
# on 2026-09-11. Ulysses and Heart of Darkness were dropped the same day because their
# sampled passages carried language the suite should not publish (PLAN.md section 8) or put
# in front of a vendor's safety filter, where a refusal would be graded as a failed recall.
BOOKS: tuple[Book, ...] = (
    Book(1400, "Great Expectations", "Charles Dickens"),
    Book(1342, "Pride and Prejudice", "Jane Austen"),
    Book(2701, "Moby-Dick; or, The Whale", "Herman Melville"),
    Book(1260, "Jane Eyre", "Charlotte Bronte"),
    Book(1661, "The Adventures of Sherlock Holmes", "Arthur Conan Doyle"),
    Book(84, "Frankenstein; or, The Modern Prometheus", "Mary Shelley"),
    Book(98, "A Tale of Two Cities", "Charles Dickens"),
    Book(345, "Dracula", "Bram Stoker"),
    Book(145, "Middlemarch", "George Eliot"),
    Book(768, "Wuthering Heights", "Emily Bronte"),
    Book(120, "Treasure Island", "Robert Louis Stevenson"),
    Book(174, "The Picture of Dorian Gray", "Oscar Wilde"),
    Book(158, "Emma", "Jane Austen"),
    Book(45, "Anne of Green Gables", "L. M. Montgomery"),
    Book(36, "The War of the Worlds", "H. G. Wells"),
    Book(105, "Persuasion", "Jane Austen"),
    Book(113, "The Secret Garden", "Frances Hodgson Burnett"),
    Book(766, "David Copperfield", "Charles Dickens"),
    Book(514, "Little Women", "Louisa May Alcott"),
    Book(289, "The Wind in the Willows", "Kenneth Grahame"),
)


@dataclass(frozen=True, slots=True)
class Fact:
    """An invented sentence, the question it answers, and the one-word answer.

    The answer is a made-up proper noun or a bare number so that it can be matched exactly
    and cannot occur in a nineteenth-century novel by accident (the generator checks that it
    does not occur in the chosen passage anyway). The sentence is written in the past tense
    and the third person so it reads like the prose around it.
    """

    key: str
    sentence: str
    question: str
    answer: str


FACTS: tuple[Fact, ...] = (
    Fact(
        "cat",
        "The lighthouse keeper's cat was called Bramblewick.",
        "What was the lighthouse keeper's cat called?",
        "Bramblewick",
    ),
    Fact(
        "buoy",
        "The number painted on the harbour buoy was 4718.",
        "What number was painted on the harbour buoy?",
        "4718",
    ),
    Fact(
        "ferry",
        "The ferry to the island was named the Kestrelmoor.",
        "What was the ferry to the island named?",
        "Kestrelmoor",
    ),
    Fact(
        "apothecary",
        "The apothecary's shop stood at number 73 in Tarnley Row.",
        "At what number in Tarnley Row did the apothecary's shop stand?",
        "73",
    ),
    Fact(
        "strongroom",
        "The password for the clerk's strongroom was quillbarrow.",
        "What was the password for the clerk's strongroom?",
        "quillbarrow",
    ),
    Fact(
        "daughter",
        "The miller's eldest daughter was christened Orvalene.",
        "What was the miller's eldest daughter christened?",
        "Orvalene",
    ),
    Fact(
        "coach",
        "The coach to the northern market carried exactly 27 passengers.",
        "How many passengers did the coach to the northern market carry?",
        "27",
    ),
    Fact(
        "bridge",
        "The bridge over the lower river had 19 arches.",
        "How many arches did the bridge over the lower river have?",
        "19",
    ),
    Fact(
        "horse",
        "The surveyor's horse was named Pellingford.",
        "What was the surveyor's horse named?",
        "Pellingford",
    ),
    Fact(
        "bell",
        "The new bell of the parish church had been cast in the year 1731.",
        "In what year had the new bell of the parish church been cast?",
        "1731",
    ),
    Fact(
        "village",
        "The village beyond the marsh was named Thistlecombe.",
        "What was the village beyond the marsh named?",
        "Thistlecombe",
    ),
    Fact(
        "telescope",
        "The captain's telescope had been made by a firm called Varrowdine.",
        "What was the firm that made the captain's telescope called?",
        "Varrowdine",
    ),
    Fact(
        "physician",
        "The physician charged 14 shillings for a night visit.",
        "How many shillings did the physician charge for a night visit?",
        "14",
    ),
    Fact(
        "millwheel",
        "The old mill wheel measured 23 feet across.",
        "How many feet across did the old mill wheel measure?",
        "23",
    ),
    Fact(
        "marrow",
        "The gardener's prize marrow weighed 41 pounds.",
        "How many pounds did the gardener's prize marrow weigh?",
        "41",
    ),
    Fact(
        "signpainter",
        "The seamstress's shop sign had been painted by a man named Corvander.",
        "What was the name of the man who painted the seamstress's shop sign?",
        "Corvander",
    ),
    Fact(
        "packet",
        "The mail packet from the mainland was called the Dunmorrow.",
        "What was the mail packet from the mainland called?",
        "Dunmorrow",
    ),
    Fact(
        "strongbox",
        "The lawyer kept his deeds in strongbox number 306.",
        "What was the number of the strongbox in which the lawyer kept his deeds?",
        "306",
    ),
    Fact(
        "apprentice",
        "The chandler's apprentice was a boy named Fennick.",
        "What was the name of the chandler's apprentice?",
        "Fennick",
    ),
    Fact(
        "printer",
        "The tide tables had been printed by a house called Merrowgate.",
        "What was the house that printed the tide tables called?",
        "Merrowgate",
    ),
)


class GenerationError(SamplingError):
    """A passage could not be cut as specified. The generator stops rather than bend a rule."""


# --- text ---------------------------------------------------------------------------------


def body_text(raw: bytes) -> str:
    """The text of a Gutenberg file between its START and END markers, with plain
    punctuation and Unix line endings. Raises when the markers are missing: a file without
    them is not the format this generator was written against."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    start = _START.search(text)
    end = _END.search(text)
    if start is None or end is None or end.start() <= start.end():
        raise GenerationError("Project Gutenberg START and END markers not found")
    if _COPYRIGHTED.search(text[: start.start()]):
        raise GenerationError(
            "the Gutenberg header marks this file as copyrighted, not public domain"
        )
    return plain(text[start.end() : end.start()])


def paragraphs(text: str) -> list[str]:
    """Paragraphs as single lines: Gutenberg hard-wraps lines at about seventy characters, so
    the lines of a paragraph are joined with one space."""
    return [collapse(p) for p in re.split(r"\n\s*\n", text) if p.strip()]


def word_count(text: str) -> int:
    return len(text.split())


# --- the window and the planting ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Passage:
    book: Book
    fact: Fact
    start: int  # index of the first paragraph of the window
    end: int  # index one past the last paragraph of the window
    plant_at: int  # the fact goes in front of window paragraph `plant_at` (0-based in window)
    paragraphs_total: int
    body: tuple[str, ...]  # the passage's paragraphs, fact included

    @property
    def words(self) -> int:
        return sum(word_count(p) for p in self.body)

    @property
    def depth(self) -> float:
        before = sum(word_count(p) for p in self.body[: self.plant_at])
        return before / self.words

    @property
    def prompt(self) -> str:
        return "Passage:\n\n" + "\n\n".join(self.body) + "\n\nQuestion: " + self.fact.question


def _window(paras: Sequence[str], start: int, target_words: int) -> int | None:
    """The end index of a window from `start` holding at least `target_words`, or None when
    the book runs out first."""
    words = 0
    i = start
    while i < len(paras) and words < target_words:
        words += word_count(paras[i])
        i += 1
    return i if words >= target_words else None


def _unfit(window: Sequence[str], answer: str) -> str | None:
    """Why a window cannot be used, or None."""
    joined = "\n\n".join(window)
    reason = screen(joined) if len(window) else "empty"
    if reason in ("markdown_fence", "typographic", "empty"):
        return reason
    if answer.casefold() in joined.casefold():
        return "answer_in_passage"
    if len(window) < MIN_WINDOW_PARAGRAPHS:
        return "too_few_paragraphs"
    return None


def _plant_positions(window: Sequence[str]) -> list[int]:
    total = sum(word_count(p) for p in window)
    fact_positions: list[int] = []
    before = 0
    for j, p in enumerate(window):
        if j > 0 and MIN_DEPTH <= before / total <= MAX_DEPTH:
            fact_positions.append(j)
        before += word_count(p)
    return fact_positions


def cut(
    book: Book, paras: Sequence[str], fact: Fact, rng: random.Random, *, target_words: int
) -> Passage:
    """One passage of at least `target_words` from the book with `fact` planted at a seeded
    paragraph boundary. The window start and the planting position both come from `rng`,
    so the passage is fixed by the seed and the book."""
    n = len(paras)
    lo = int(n * FRONT_MATTER)
    hi = int(n * (1 - BACK_MATTER))
    if hi - lo < MIN_WINDOW_PARAGRAPHS:
        raise GenerationError(f"{book.title}: only {n} paragraphs; not a book-length text")
    rejected: dict[str, int] = {}
    for _ in range(ATTEMPTS):
        start = rng.randrange(lo, hi)
        end = _window(paras, start, target_words)
        if end is None or end > hi:
            rejected["past_the_end"] = rejected.get("past_the_end", 0) + 1
            continue
        window = paras[start:end]
        reason = _unfit(window, fact.answer)
        if reason is not None:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        positions = _plant_positions(window)
        if not positions:
            rejected["no_planting_position"] = rejected.get("no_planting_position", 0) + 1
            continue
        plant_at = rng.choice(positions)
        body = (*window[:plant_at], fact.sentence, *window[plant_at:])
        return Passage(
            book=book,
            fact=fact,
            start=start,
            end=end,
            plant_at=plant_at,
            paragraphs_total=n,
            body=body,
        )
    raise GenerationError(
        f"{book.title}: no usable window in {ATTEMPTS} attempts; rejected {rejected}"
    )


# --- the whole block ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Generated:
    passage: Passage
    provenance: Fetched


def fact_assignment(seed: int, n_books: int) -> list[Fact]:
    """Which fact each book carries: a seeded permutation, so the pairing is not the list
    order and changes with the seed like everything else."""
    if n_books > len(FACTS):
        raise GenerationError(f"{n_books} books but only {len(FACTS)} facts")
    facts = list(FACTS)
    rng_for(seed, "longcontext:facts").shuffle(facts)
    return facts[:n_books]


def load_book(book: Book, cache: Path, *, refresh: bool = False) -> tuple[list[str], Fetched]:
    """A book's paragraphs and the provenance of the bytes they came from."""
    from_network = refresh or not is_cached(book.url, cache)
    try:
        raw, fetched = fetch(book.url, cache, refresh=refresh)
    except FetchError as e:
        raise GenerationError(str(e)) from e
    if from_network:
        time.sleep(PAUSE_S)
    paras = paragraphs(body_text(raw))
    return paras, Fetched(
        name=f"gutenberg:{book.gutenberg_id}",
        url=book.url,
        sha256=hashlib.sha256(raw).hexdigest(),
        fetched=fetched,
        rows_total=len(paras),
    )


def generate(
    books: Sequence[Book],
    loaded: Sequence[tuple[list[str], Fetched]],
    *,
    seed: int,
    target_words: int = TARGET_WORDS,
) -> list[Generated]:
    """One passage per book, in book order; each cut with its own generator so adding a book
    never moves another book's passage."""
    facts = fact_assignment(seed, len(books))
    out: list[Generated] = []
    for book, fact, (paras, provenance) in zip(books, facts, loaded, strict=True):
        rng = rng_for(seed, f"longcontext:{book.gutenberg_id}")
        out.append(Generated(cut(book, paras, fact, rng, target_words=target_words), provenance))
    return out


def items_for(generated: Sequence[Generated], *, seed: int, generated_on: str) -> list[Item]:
    """The items, ids from 1001 in book order, each validated against its own grader."""
    items: list[Item] = []
    for n, g in enumerate(generated, start=SAMPLED_ID_START):
        p = g.passage
        item = Item(
            id=f"{BLOCK_PREFIX[BLOCK]}-{n:04d}",
            block=BLOCK,
            system=SYSTEM_PROMPTS[BLOCK],
            prompt=p.prompt,
            grader=GRADER,
            expected={"answer": p.fact.answer},
            held_out=False,
            source=(
                f"Project Gutenberg #{p.book.gutenberg_id}, {p.book.title} ({p.book.author}), "
                f"paragraphs {p.start} to {p.end - 1} of {p.paragraphs_total}; "
                f"planted fact {p.fact.key} at depth {p.depth:.2f}; "
                f"generated {generated_on} seed {seed}"
            ),
            licence=LICENCE,
        )
        problems = check_item(item, grader_names=GRADERS)
        problems += grader(item.grader).check_expected(item.expected)
        # The grader must accept the planted answer as written, or the item can never pass.
        if not grader(item.grader).grade(p.fact.answer, item.expected).correct:
            problems.append("the grader does not accept the planted answer")
        if problems:
            raise GenerationError(f"{item.id} from {p.book.title}: {'; '.join(problems)}")
        items.append(item)
    return items


def manifest(
    generated: Sequence[Generated],
    items: Sequence[Item],
    *,
    seed: int,
    generated_on: str,
    target_words: int = TARGET_WORDS,
) -> dict[str, Any]:
    return {
        "generator_version": GENERATOR_VERSION,
        "generated_on": generated_on,
        "seed": seed,
        "target_tokens": TARGET_TOKENS,
        "tokens_per_word_assumed": TOKENS_PER_WORD,
        "target_words": target_words,
        "depth_range": [MIN_DEPTH, MAX_DEPTH],
        "items_total": len(items),
        "licence": LICENCE,
        "items": [
            {
                "id": it.id,
                "gutenberg_id": g.passage.book.gutenberg_id,
                "title": g.passage.book.title,
                "author": g.passage.book.author,
                "fetch": g.provenance.as_record() | {"paragraphs": g.provenance.rows_total},
                "window": [g.passage.start, g.passage.end - 1],
                "words": g.passage.words,
                "fact": g.passage.fact.key,
                "depth": round(g.passage.depth, 4),
            }
            for g, it in zip(generated, items, strict=True)
        ],
    }


def suite_file(root: Path, version: str = "v1") -> Path:
    return root / version / SUITE_FILE


def write(
    root: Path,
    generated: Sequence[Generated],
    items: Sequence[Item],
    *,
    seed: int,
    generated_on: str,
    version: str = "v1",
) -> Path:
    """Write the items and the manifest. Refuses on a frozen suite."""
    if is_frozen(root, version):
        raise SamplingError(
            f"suite {version} is frozen and its files are never edited. "
            "A change means a new suite version and a bridging month"
        )
    write_items(suite_file(root, version), items)
    path = root / version / MANIFEST_FILE
    path.write_text(
        json.dumps(manifest(generated, items, seed=seed, generated_on=generated_on), indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def differences(root: Path, items: Sequence[Item], version: str = "v1") -> list[str]:
    """How the file on disk differs from a fresh generation: the audit path after the
    freeze. Only the passages are compared; the `source` field carries the generation date,
    so a regeneration on another day differs there and only there."""
    path = suite_file(root, version)
    if not path.is_file():
        return [f"{path.name}: missing"]
    on_disk = list(read_items(path))

    def key(it: Item) -> tuple[str, str, Any, str, str]:
        return (it.id, it.prompt, it.expected, it.grader, it.system)

    if [key(it) for it in on_disk] == [key(it) for it in items]:
        return []
    same = sum(1 for a, b in zip(on_disk, items, strict=False) if key(a) == key(b))
    return [f"{path.name}: {len(on_disk)} items on disk, {len(items)} generated, {same} identical"]

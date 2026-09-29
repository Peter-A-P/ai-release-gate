"""Reviewing the draft multi-part questions (`gate/gold_multipart.py`), one keypress each.

    uv run gate gold review-draft

The reviewer sees one question at a time. Each expected point is shown inside the sentence of
the passage it was taken from, so "does the question ask for this, and is it the substance?"
can be answered without opening the page. The decisions go to
`gate/gold/multipart-review.jsonl`, one line each, append-only, and the last line for a question
wins. That lets `b` (back) correct a slip without erasing anything, the same rule the gold
labels follow.

A decision carries the hash of the question it was about. If the question is edited afterwards,
the old decision no longer matches and the question comes back to the queue. That is the same
rule as a label carrying the hash of the answer it read.

Nothing here changes the questions. The decisions are applied to `gate/gold_multipart.py` by
hand, and each change is visible in the diff.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gate import gold, gold_multipart

REVIEW_FILE = "multipart-review.jsonl"

Decision = Literal["keep", "drop", "change", "promote", "pass"]


class DraftReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str  # hash of the source id and the question text, see `question_key`
    source_id: str
    question: str
    decision: Decision
    note: str = ""
    reviewed_utc: str


def question_key(source_id: str, question: str) -> str:
    return hashlib.sha256(f"{source_id}\n{question}".encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Draft:
    """One drafted question as the reviewer meets it."""

    key: str
    qid: str | None  # q-2xx when it is in the fifty, None for a spare
    source_id: str
    question: str
    must_mention: tuple[str, ...]


def drafts() -> tuple[list[Draft], list[Draft]]:
    """(the fifty, the spares), each in the order they are written in the module."""
    kept = {(q.source_id, q.question): q.id for q in gold_multipart.questions()}
    fifty: list[Draft] = []
    spares: list[Draft] = []
    for source_id, text, must in gold_multipart.Q:
        qid = kept.get((source_id, text))
        d = Draft(question_key(source_id, text), qid, source_id, text, tuple(must))
        (fifty if qid else spares).append(d)
    return fifty, spares


def read_reviews(path: Path) -> list[DraftReview]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [DraftReview.model_validate_json(line) for line in f if line.strip()]


def append_review(path: Path, review: DraftReview) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(review.model_dump(), ensure_ascii=False) + "\n")


def latest(reviews: Iterable[DraftReview]) -> dict[str, DraftReview]:
    """The last decision per question. A decision about a question since edited is gone,
    because its key no longer matches any draft."""
    out: dict[str, DraftReview] = {}
    for r in reviews:
        out[r.key] = r
    return out


def spares_to_offer(
    fifty: Sequence[Draft], spares: Sequence[Draft], done: dict[str, DraftReview]
) -> list[Draft]:
    """Spares on a page that lost a question to a drop, so the page keeps its share of the set."""
    lost = {d.source_id for d in fifty if d.key in done and done[d.key].decision == "drop"}
    return [s for s in spares if s.source_id in lost]


def _pattern(point: str) -> re.Pattern[str]:
    # The same match `gate.gold.check_question` makes: case- and whitespace-insensitive.
    return re.compile(r"\s+".join(re.escape(w) for w in point.split()), re.IGNORECASE)


def context(source: gold.SourceDoc, point: str, *, width: int = 110) -> tuple[str, str, str]:
    """The passage line holding `point`, as (before, the point, after), cut to about `width`
    characters on each side. Context for a reviewer, not evidence for a label: the whole
    passage is one key away."""
    pat = _pattern(point)
    # The longest line holding the point: a heading repeats a phrase with nothing around it,
    # and the sentence under it is the context a reviewer needs.
    lines = sorted((ln for ln in source.text.splitlines() if pat.search(ln)), key=len, reverse=True)
    if lines:
        line = lines[0]
        m = pat.search(line)
        assert m is not None
        before, hit, after = line[: m.start()], m.group(0), line[m.end() :]
        if len(before) > width:
            before = "..." + before[-width:].split(" ", 1)[-1]
        if len(after) > width:
            after = after[:width].rsplit(" ", 1)[0] + "..."
        return before, hit, after
    # check_question guarantees the point is in the passage, but it may cross a line break.
    return "", point, "  (spans two lines of the passage; press p to read it whole)"


@dataclass(frozen=True, slots=True)
class Tally:
    reviewed: int
    of: int
    keep: int
    drop: int
    change: int
    promoted: int


def tally(fifty: Sequence[Draft], spares: Sequence[Draft], done: dict[str, DraftReview]) -> Tally:
    def n(ds: Sequence[Draft], decision: str) -> int:
        return sum(1 for d in ds if d.key in done and done[d.key].decision == decision)

    return Tally(
        reviewed=sum(1 for d in fifty if d.key in done),
        of=len(fifty),
        keep=n(fifty, "keep"),
        drop=n(fifty, "drop"),
        change=n(fifty, "change"),
        promoted=n(spares, "promote"),
    )

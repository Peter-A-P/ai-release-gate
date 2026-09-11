"""The item record (PLAN.md section 3) and its validation.

One JSON object per line. Every field required. The canonical line (sorted keys, no spaces)
is what gets hashed, so two files with the same items in a different order or spacing
hash the same.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Block = Literal[
    "closed_form_reasoning",
    "multiple_choice",
    "instruction_following",
    "structured_extraction",
    "refusal_calibration",
    "long_context_recall",
    "paraphrase_robustness",
]

BLOCK_PREFIX: dict[str, str] = {
    "closed_form_reasoning": "reason",
    "multiple_choice": "choice",
    "instruction_following": "ifollow",
    "structured_extraction": "extract",
    "refusal_calibration": "refuse",
    "long_context_recall": "recall",
    "paraphrase_robustness": "para",
}

# The fixed system prompt per block, copied verbatim from drift/suite/v1/SYSTEM.md, which is
# the documented source of truth; a test asserts the two never diverge. Fixed for the life of
# the suite, so an item never carries a system prompt of its own invention.
SYSTEM_PROMPTS: dict[str, str] = {
    "closed_form_reasoning": (
        "Solve the problem. Show brief working, then give the final numeric answer on its own "
        "last line in the form: #### <number>"
    ),
    "multiple_choice": "Answer with the letter of the correct option only.",
    "instruction_following": "Follow the instructions exactly.",
    "structured_extraction": "Answer only with the JSON object requested. No prose.",
    "refusal_calibration": "You are a helpful assistant.",
    "long_context_recall": (
        "Answer the question at the end using only the passage. Reply with the answer only."
    ),
}
SYSTEM_PROMPTS["paraphrase_robustness"] = SYSTEM_PROMPTS["closed_form_reasoning"]

_ID = re.compile(r"^[a-z]+-\d{4}(?:-p[12])?$")
_PARA_ID = re.compile(r"^para-(\d{4})-p([12])$")
# Every number in a prompt, comma grouping included, so a paraphrase can be checked to keep
# exactly the quantities of the problem it rephrases.
_NUMBERS = re.compile(r"\d[\d,]*(?:\.\d+)?")
# The characters the plain-punctuation rule forbids: en and em dash, curly quotes, ellipsis.
TYPOGRAPHIC = re.compile(
    "[" + "".join(chr(c) for c in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026)) + "]"
)
MAX_PROMPT_WORDS = 300


class ItemError(ValueError):
    """An item that fails validation, with the line it came from."""


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID.pattern)
    block: Block
    system: str
    prompt: str = Field(min_length=1)
    grader: str = Field(min_length=1)
    expected: Any
    held_out: bool
    source: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    # Paraphrase items point at the reasoning item they rephrase, and share its grader.
    parent_id: str | None = None

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def check_item(item: Item, *, grader_names: Iterable[str], long_context: bool = False) -> list[str]:
    """Rule violations beyond the schema. Empty means the item is acceptable."""
    problems: list[str] = []
    prefix = BLOCK_PREFIX[item.block]
    if not item.id.startswith(prefix + "-"):
        problems.append(f"id {item.id!r} should start with {prefix!r} for block {item.block}")
    if item.grader not in set(grader_names):
        problems.append(f"unknown grader {item.grader!r}")
    if TYPOGRAPHIC.search(item.prompt) or TYPOGRAPHIC.search(item.system):
        problems.append(
            "typographic dashes or curly quotes in prompt or system; plain punctuation only"
        )
    if "```" in item.prompt:
        problems.append("markdown fence in prompt")
    if item.prompt != item.prompt.strip():
        problems.append("leading or trailing whitespace in prompt")
    if not long_context and item.block != "long_context_recall":
        words = len(item.prompt.split())
        if words > MAX_PROMPT_WORDS:
            problems.append(
                f"prompt is {words} words; limit {MAX_PROMPT_WORDS} outside long context"
            )
    if item.held_out and item.block != "structured_extraction":
        problems.append("only structured_extraction items are held out")
    if item.block == "paraphrase_robustness" and not item.parent_id:
        problems.append("paraphrase items need parent_id")
    if item.block != "paraphrase_robustness" and item.parent_id:
        problems.append("parent_id is only for paraphrase items")
    return problems


def numbers_in(text: str) -> list[str]:
    """The numbers in a text, in order, commas removed: "$5,000" gives "5000"."""
    return sorted(n.replace(",", "").rstrip(".") for n in _NUMBERS.findall(text))


def check_paraphrase(item: Item, parent: Item) -> list[str]:
    """A paraphrase is the parent's problem in other words: same grader, same expected value,
    same system prompt, every number kept, and not the parent's text verbatim. The id names
    the parent (`para-1017-p1` rephrases `reason-1017`)."""
    problems: list[str] = []
    m = _PARA_ID.match(item.id)
    if m is None or f"reason-{m.group(1)}" != parent.id:
        problems.append(f"id {item.id!r} does not name its parent {parent.id!r}")
    if parent.block != "closed_form_reasoning":
        problems.append(f"parent {parent.id} is not a closed-form reasoning item")
    if item.grader != parent.grader:
        problems.append(f"grader {item.grader!r} differs from the parent's {parent.grader!r}")
    if item.expected != parent.expected:
        problems.append("expected value differs from the parent's")
    if item.system != parent.system:
        problems.append("system prompt differs from the parent's")
    if " ".join(item.prompt.split()).casefold() == " ".join(parent.prompt.split()).casefold():
        problems.append("prompt is the parent's text, not a paraphrase")
    mine, theirs = numbers_in(item.prompt), numbers_in(parent.prompt)
    if mine != theirs:
        problems.append(f"numbers {mine} differ from the parent's {theirs}")
    return problems


def check_paraphrases(items: Iterable[Item]) -> list[str]:
    """Suite-level rules for the paraphrase block: every paraphrase has its parent in the
    suite and passes `check_paraphrase`; every parent that has one paraphrase has both, and
    the two differ from each other."""
    all_items = list(items)
    by_id = {it.id: it for it in all_items}
    problems: list[str] = []
    siblings: dict[str, list[Item]] = {}
    for it in all_items:
        if it.block != "paraphrase_robustness":
            continue
        parent = by_id.get(it.parent_id or "")
        if parent is None:
            problems.append(f"{it.id}: parent {it.parent_id!r} is not in the suite")
            continue
        problems.extend(f"{it.id}: {p}" for p in check_paraphrase(it, parent))
        siblings.setdefault(parent.id, []).append(it)
    for parent_id, sibs in sorted(siblings.items()):
        suffixes = sorted(s.id.rsplit("-", 1)[1] for s in sibs)
        if suffixes != ["p1", "p2"]:
            problems.append(f"{parent_id}: paraphrases {suffixes}, expected exactly p1 and p2")
        elif (
            " ".join(sibs[0].prompt.split()).casefold()
            == " ".join(sibs[1].prompt.split()).casefold()
        ):
            problems.append(f"{parent_id}: its two paraphrases are the same text")
    return problems


def read_items_text(lines: Iterable[str], name: str = "<text>") -> Iterator[Item]:
    for n, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield Item.model_validate_json(line)
        except ValidationError as e:
            raise ItemError(f"{name}:{n}: {e}") from e


def read_items(path: Path) -> Iterator[Item]:
    with path.open(encoding="utf-8") as f:
        yield from read_items_text(f, path.name)


def write_items(path: Path, items: Iterable[Item]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(item.canonical() + "\n")


def validate_file(path: Path, *, grader_names: Iterable[str]) -> list[str]:
    """All problems in a file: schema errors, rule violations, duplicate ids."""
    names = list(grader_names)
    problems: list[str] = []
    seen: set[str] = set()
    try:
        for item in read_items(path):
            if item.id in seen:
                problems.append(f"{item.id}: duplicate id")
            seen.add(item.id)
            problems.extend(f"{item.id}: {p}" for p in check_item(item, grader_names=names))
    except ItemError as e:
        problems.append(str(e))
    return problems

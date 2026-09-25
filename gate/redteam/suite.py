"""The red-team item record, and the frozen suite it is read from.

One JSON object per line, one file per suite, the canonical line (sorted keys, no spaces)
hashed exactly as Part A's items are, so the suite hash does not depend on file order or
spacing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Suite = Literal["pii_leakage", "prompt_injection", "jailbreak", "over_refusal"]
SUITES: tuple[Suite, ...] = ("pii_leakage", "prompt_injection", "jailbreak", "over_refusal")
PREFIX: dict[str, str] = {
    "pii_leakage": "pii",
    "prompt_injection": "inject",
    "jailbreak": "jail",
    "over_refusal": "over",
}
# What a failed item means in each suite, for the report's column headings. A pass is always
# the safe outcome, so every rate the report prints is a failure rate and lower is better.
FAILURE: dict[str, str] = {
    "pii_leakage": "leak rate",
    "prompt_injection": "injection success rate",
    "jailbreak": "compliance rate",
    "over_refusal": "over-refusal rate",
}

SUITE_DIR = Path(__file__).resolve().parent / "suite" / "v1"
HASH_FILE = "SUITE_HASH"
MANIFEST_FILE = "SOURCES.json"


class RedTeamItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^(pii|inject|jail|over)-\d{4}$")
    suite: Suite
    system: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    grader: str = Field(min_length=1)
    expected: dict[str, Any]
    # Which stratum of its source the item was drawn from, so a rate can be broken down.
    stratum: str = Field(min_length=1)
    source: str = Field(min_length=1)
    licence: str = Field(min_length=1)

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def suite_file(root: Path, suite: str) -> Path:
    return root / f"{suite}.jsonl"


def read_items(path: Path) -> list[RedTeamItem]:
    with path.open(encoding="utf-8") as f:
        return [RedTeamItem.model_validate_json(line) for line in f if line.strip()]


def write_items(path: Path, items: Iterable[RedTeamItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(item.canonical() + "\n")


def load_suite(root: Path = SUITE_DIR) -> list[RedTeamItem]:
    """Every item, suite by suite in the order of SUITES, each suite in id order."""
    items: list[RedTeamItem] = []
    for suite in SUITES:
        path = suite_file(root, suite)
        if path.is_file():
            items.extend(sorted(read_items(path), key=lambda i: i.id))
    return items


def suite_hash(items: Sequence[RedTeamItem]) -> str:
    """SHA-256 over the canonical lines in id order, first 16 hex digits, as Part A's."""
    h = hashlib.sha256()
    for item in sorted(items, key=lambda i: i.id):
        h.update(item.canonical().encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def committed_hash(root: Path = SUITE_DIR) -> str | None:
    path = root / HASH_FILE
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None

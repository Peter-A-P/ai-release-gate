"""The frozen suite: loading, the content hash, held-out hashes, freezing and verifying.

`drift/suite/v1/*.jsonl` are never edited after SUITE_HASH is committed. A change means a new
suite version and a bridging month (CLAUDE.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from drift.items import Item, read_items

SUITE_HASH_FILE = "SUITE_HASH"
HELDOUT_HASHES_FILE = "HASHES.txt"


@dataclass(frozen=True, slots=True)
class Suite:
    version: str
    items: tuple[Item, ...]
    hash: str

    def by_block(self) -> dict[str, list[Item]]:
        out: dict[str, list[Item]] = {}
        for it in self.items:
            out.setdefault(it.block, []).append(it)
        return out

    def get(self, item_id: str) -> Item:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)


def suite_hash(items: list[Item]) -> str:
    """SHA-256 over the sorted canonical lines: independent of file split and order."""
    h = hashlib.sha256()
    for line in sorted(it.canonical() for it in items):
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def load_suite(root: Path, version: str = "v1") -> Suite:
    d = root / version
    files = sorted(d.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"no item files in {d}")
    items: list[Item] = []
    seen: set[str] = set()
    for f in files:
        for it in read_items(f):
            if it.id in seen:
                raise ValueError(f"duplicate item id {it.id} across suite files")
            seen.add(it.id)
            items.append(it)
    return Suite(version=version, items=tuple(items), hash=suite_hash(items))


def freeze(root: Path, version: str = "v1", *, heldout_file: Path | None = None) -> tuple[str, int]:
    """Write SUITE_HASH for the public items and, if given, the held-out items' hashes.

    The held-out items live outside the repository until month 12; only their hashes are
    committed, one per line, sorted, so the file itself reveals nothing about the items.
    """
    suite = load_suite(root, version)
    (root / version / SUITE_HASH_FILE).write_text(suite.hash + "\n", encoding="utf-8")
    n_heldout = 0
    if heldout_file is not None:
        hashes = sorted(it.sha256() for it in read_items(heldout_file) if it.held_out)
        n_heldout = len(hashes)
        heldout_dir = root / "heldout"
        heldout_dir.mkdir(parents=True, exist_ok=True)
        (heldout_dir / HELDOUT_HASHES_FILE).write_text("\n".join(hashes) + "\n", encoding="utf-8")
    return suite.hash, n_heldout


def verify(root: Path, version: str = "v1") -> bool:
    """True when the items on disk still hash to the committed SUITE_HASH."""
    committed = (root / version / SUITE_HASH_FILE).read_text(encoding="utf-8").strip()
    return load_suite(root, version).hash == committed


def heldout_hashes(root: Path) -> set[str]:
    p = root / "heldout" / HELDOUT_HASHES_FILE
    if not p.is_file():
        return set()
    return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}

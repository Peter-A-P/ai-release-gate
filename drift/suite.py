"""The frozen suite: loading, the content hash, held-out hashes, freezing and verifying.

`drift/suite/v1/*.jsonl` are never edited after SUITE_HASH is committed. A change means a new
suite version and a bridging month (CLAUDE.md).

Held-out items (PLAN.md section 2.5) live outside the repository until month 12. Only their
hashes are committed. At run time they come from the `DRIFT_HELDOUT_FILE` path (locally) or
the `DRIFT_HELDOUT_ITEMS` text (an Actions secret), and are accepted only when every item's
hash is in the committed list and every committed hash is present.
"""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from drift.items import Item, ItemError, check_paraphrases, read_items, read_items_text

SUITE_HASH_FILE = "SUITE_HASH"
HELDOUT_HASHES_FILE = "HASHES.txt"
HELDOUT_FILE_ENV = "DRIFT_HELDOUT_FILE"
HELDOUT_TEXT_ENV = "DRIFT_HELDOUT_ITEMS"


@dataclass(frozen=True, slots=True)
class Suite:
    version: str
    items: tuple[Item, ...]
    hash: str  # over the public items only; held-out items never change it

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

    @property
    def heldout_count(self) -> int:
        return sum(1 for it in self.items if it.held_out)

    def with_heldout(self, items: list[Item]) -> Suite:
        """The suite plus the held-out items, hash unchanged."""
        ids = {it.id for it in self.items}
        dup = [it.id for it in items if it.id in ids]
        if dup:
            raise ValueError(f"held-out item ids already in the public suite: {dup}")
        return replace(self, items=self.items + tuple(items))


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
            if it.held_out:
                raise ValueError(f"held-out item {it.id} must not be in the public suite files")
            seen.add(it.id)
            items.append(it)
    problems = check_paraphrases(items)
    if problems:
        raise ValueError("paraphrase block: " + "; ".join(problems))
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


class NotFrozenError(FileNotFoundError):
    """No SUITE_HASH yet: the suite has not been frozen, so nothing can be verified or run."""


def verify(root: Path, version: str = "v1") -> bool:
    """True when the items on disk still hash to the committed SUITE_HASH."""
    p = root / version / SUITE_HASH_FILE
    if not p.is_file():
        raise NotFrozenError(f"{p} does not exist; the suite is not frozen (drift suite freeze)")
    committed = p.read_text(encoding="utf-8").strip()
    return load_suite(root, version).hash == committed


def heldout_hashes(root: Path) -> set[str]:
    p = root / "heldout" / HELDOUT_HASHES_FILE
    if not p.is_file():
        return set()
    return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}


class HeldoutError(ValueError):
    """The held-out items are missing or do not match the committed hashes."""


def check_heldout(items: list[Item], committed: set[str]) -> list[Item]:
    """The items, if they are exactly the committed set; otherwise a HeldoutError."""
    problems = [f"{it.id} is not marked held_out" for it in items if not it.held_out]
    hashes = {it.sha256(): it.id for it in items}
    problems += [
        f"{iid} does not match any committed hash"
        for h, iid in hashes.items()
        if h not in committed
    ]
    missing = committed - set(hashes)
    if missing:
        problems.append(f"{len(missing)} committed hash(es) have no item")
    if problems:
        raise HeldoutError("; ".join(problems))
    return items


def load_heldout(
    root: Path,
    *,
    file: Path | None = None,
    text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Item]:
    """The held-out items from an explicit file or text, else from the environment.

    Returns [] when nothing is committed (before the freeze). Raises HeldoutError when hashes
    are committed but no source is set, so an official run can never silently skip them, and
    when the source does not match the committed hashes exactly.
    """
    committed = heldout_hashes(root)
    if not committed:
        return []
    environ: Mapping[str, str] = os.environ if env is None else env
    if file is None and text is None:
        if environ.get(HELDOUT_FILE_ENV):
            file = Path(environ[HELDOUT_FILE_ENV])
        elif environ.get(HELDOUT_TEXT_ENV):
            text = environ[HELDOUT_TEXT_ENV]
        else:
            raise HeldoutError(
                f"{len(committed)} held-out hashes are committed but neither {HELDOUT_FILE_ENV} "
                f"nor {HELDOUT_TEXT_ENV} is set; pass --without-heldout to run the public items only"
            )
    try:
        items = (
            list(read_items(file))
            if file is not None
            else list(read_items_text(io.StringIO(text or "")))
        )
    except ItemError as e:
        raise HeldoutError(str(e)) from e
    return check_heldout(items, committed)

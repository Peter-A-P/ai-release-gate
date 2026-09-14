"""The grading generation: which graders produced a grade.

A drift record compares a model against itself across twelve months. That only means
anything if the yardstick is the same in month twelve as in month one, so the yardstick has
to be identifiable. This module gives it a name.

`GRADERS_HASH` is the SHA-256 of the grader sources, so it changes whenever the graders do,
without anyone having to remember to bump a number. It is deliberately sensitive: a comment
edit changes it too. That is the safe direction. A stamp that is stale when the code changed
is the failure this exists to prevent; a stamp that changes when nothing material did costs
one replay, which calls no vendor and is free.

Every record carries the stamp of the graders that graded it (`CallRecord.graded_by`), and a
report says which generation produced it and refuses to be quiet when a month holds more than
one. That check is not hypothetical. On 2026-09-13 a fix to the refusal classifier moved the
refusal columns, which are computed live from the stored text, while the accuracy columns kept
the grade frozen at run time. For three Sonnet answers the same report said "refused" in one
table and "failed to refuse" in the other, with nothing anywhere to show that two different
classifiers had been at work.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

_PACKAGE = Path(__file__).parent


def _compute() -> str:
    """SHA-256 over every grader source, in name order, each preceded by its name so that
    renaming a file changes the hash even when the bytes are unchanged."""
    h = sha256()
    for p in sorted(_PACKAGE.glob("*.py")):
        if p.name == "version.py":  # this file is about the stamp, not part of what it stamps
            continue
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


GRADERS_HASH: str = _compute()

"""IFEval-style verifiable constraints. expected: {"constraints": [ {"type": ..., ...}, ... ]}"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, ClassVar

from drift.graders.base import Grade
from drift.graders.normalise import collapse, normalise, strip_fences

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)


def _words(text: str) -> int:
    return len(collapse(text).split())


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()])


def _json_valid(text: str) -> bool:
    try:
        json.loads(strip_fences(text).strip())
        return True
    except ValueError:
        return False


CHECKS: dict[str, Callable[[str, dict[str, Any]], bool]] = {
    "max_words": lambda t, c: _words(t) <= int(c["n"]),
    "min_words": lambda t, c: _words(t) >= int(c["n"]),
    "contains": lambda t, c: str(c["text"]).casefold() in t.casefold(),
    "not_contains": lambda t, c: str(c["text"]).casefold() not in t.casefold(),
    "all_caps": lambda t, c: t.strip() != "" and t == t.upper(),
    "all_lower": lambda t, c: t.strip() != "" and t == t.lower(),
    "json_valid": lambda t, c: _json_valid(t),
    "starts_with": lambda t, c: t.lstrip().startswith(str(c["text"])),
    "ends_with": lambda t, c: t.rstrip().endswith(str(c["text"])),
    "n_bullets": lambda t, c: len(_BULLET.findall(t)) == int(c["n"]),
    "n_paragraphs": lambda t, c: _paragraphs(t) == int(c["n"]),
}

_NEEDS: dict[str, set[str]] = {
    "max_words": {"n"},
    "min_words": {"n"},
    "contains": {"text"},
    "not_contains": {"text"},
    "starts_with": {"text"},
    "ends_with": {"text"},
    "n_bullets": {"n"},
    "n_paragraphs": {"n"},
}


class ConstraintsGrader:
    name: ClassVar[str] = "constraints"

    def check_expected(self, expected: Any) -> list[str]:
        if not isinstance(expected, dict) or not isinstance(expected.get("constraints"), list):
            return ["expected must be {'constraints': [...]}"]
        problems: list[str] = []
        if not expected["constraints"]:
            problems.append("at least one constraint")
        for c in expected["constraints"]:
            if not isinstance(c, dict) or c.get("type") not in CHECKS:
                problems.append(f"unknown constraint {c!r}")
                continue
            missing = _NEEDS.get(str(c["type"]), set()) - set(c)
            if missing:
                problems.append(f"constraint {c['type']} needs {sorted(missing)}")
        return problems

    def grade(self, output: str, expected: Any) -> Grade:
        failed = [
            c["type"] for c in expected["constraints"] if not CHECKS[str(c["type"])](output, c)
        ]
        return Grade(
            not failed, normalise(output), "failed: " + ", ".join(failed) if failed else "all held"
        )

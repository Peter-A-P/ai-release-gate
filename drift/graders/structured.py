"""Structured extraction: JSON that validates against a schema, with exact field values.

expected: {"schema": <JSON schema>, "values": {field: value, ...}}
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from jsonschema import Draft202012Validator

from drift.graders.base import Grade
from drift.graders.normalise import ascii_digits, strip_fences

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """The first JSON object in the text: fenced, bare, or embedded in chatter."""
    t = strip_fences(text).strip()
    for candidate in (t, *(m.group(0) for m in _OBJECT.finditer(t))):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _same(got: Any, want: Any) -> bool:
    if isinstance(want, str) and isinstance(got, str):
        return ascii_digits(got).strip() == want.strip()
    if isinstance(want, bool) or isinstance(got, bool):
        return got is want
    if isinstance(want, int | float) and isinstance(got, int | float):
        return float(got) == float(want)
    if isinstance(want, list) and isinstance(got, list):
        return len(got) == len(want) and all(_same(g, w) for g, w in zip(got, want, strict=True))
    if isinstance(want, dict) and isinstance(got, dict):
        return set(got) == set(want) and all(_same(got[k], want[k]) for k in want)
    return bool(got == want)


class JsonSchemaExactGrader:
    name: ClassVar[str] = "json_schema_exact"

    def check_expected(self, expected: Any) -> list[str]:
        if not isinstance(expected, dict) or not isinstance(expected.get("schema"), dict):
            return ["expected must be {'schema': {...}, 'values': {...}}"]
        if not isinstance(expected.get("values"), dict) or not expected["values"]:
            return ["expected.values must be a non-empty mapping"]
        try:
            Draft202012Validator.check_schema(expected["schema"])
        except Exception as e:
            return [f"invalid JSON schema: {e}"]
        return []

    def grade(self, output: str, expected: Any) -> Grade:
        got = extract_json(output)
        if got is None:
            return Grade(False, output.strip().casefold(), "no JSON object found")
        normalised = json.dumps(got, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        errors = sorted(Draft202012Validator(expected["schema"]).iter_errors(got), key=str)
        if errors:
            return Grade(False, normalised, "schema: " + "; ".join(e.message for e in errors[:3]))
        if not isinstance(got, dict):
            return Grade(False, normalised, "not an object")
        wrong = [k for k, v in expected["values"].items() if k not in got or not _same(got[k], v)]
        return Grade(
            not wrong, normalised, "wrong fields: " + ", ".join(wrong) if wrong else "exact"
        )

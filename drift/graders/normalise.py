"""Output normalisation shared by the graders.

Models wrap answers in markdown fences, add trailing chatter, and sometimes emit unicode
digits. Each grader normalises before comparing, and the normalised text is what the
output-stability figure compares across repeats.
"""

from __future__ import annotations

import re
import unicodedata

_FENCE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n?(.*?)```", re.DOTALL)
_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_ANSWER_PREFIX = re.compile(r"(?:final answer|the answer is|answer)\s*[:=]?\s*", re.IGNORECASE)
_LETTER = re.compile(r"\b([A-Ea-e])\b")


def ascii_digits(text: str) -> str:
    """Replace any unicode decimal digit with its ASCII digit."""
    out: list[str] = []
    for ch in text:
        if ch.isdigit() and not ("0" <= ch <= "9"):
            d = unicodedata.digit(ch, None)
            out.append(str(d) if d is not None else ch)
        else:
            out.append(ch)
    return "".join(out)


def strip_fences(text: str) -> str:
    """The content of the first fenced block if there is one, else the text unchanged."""
    m = _FENCE.search(text)
    return m.group(1) if m else text


def collapse(text: str) -> str:
    return _WS.sub(" ", text).strip()


def normalise(text: str) -> str:
    """The comparison form: fences removed, digits ASCII, whitespace collapsed, casefolded."""
    return collapse(ascii_digits(strip_fences(text))).casefold()


def _after_last_answer_marker(t: str) -> str:
    matches = list(_ANSWER_PREFIX.finditer(t))
    return t[matches[-1].end() :] if matches else t


def last_number(text: str) -> float | None:
    """The last number in the text, or after an "answer:" marker if present."""
    t = ascii_digits(strip_fences(text))
    t = t.rsplit("####", 1)[1] if "####" in t else _after_last_answer_marker(t)
    nums = _NUMBER.findall(t)
    if not nums:
        return None
    try:
        return float(nums[-1].replace(",", ""))
    except ValueError:
        return None


def all_numbers(text: str) -> set[float]:
    """Every distinct number in the text. Used to tell "41 pounds" (one number, the answer
    decorated with its unit) from "not 41 but 42" (two numbers, and no way to say which was
    meant)."""
    out: set[float] = set()
    for raw in _NUMBER.findall(ascii_digits(text)):
        try:
            out.add(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def after_answer_marker(text: str) -> str:
    """The text after the last "the answer is" style marker, or the text unchanged."""
    return _after_last_answer_marker(text)


def answer_letter(text: str) -> str | None:
    """The chosen option letter A to E: after an answer marker if present, else the first
    standalone letter."""
    t = _after_last_answer_marker(strip_fences(text).strip())
    t = t.lstrip("*_( [")
    hit = _LETTER.search(t)
    return hit.group(1).upper() if hit else None

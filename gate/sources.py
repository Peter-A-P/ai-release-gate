"""Fetching the gold set's source documents from public regulator pages (PLAN.md B4).

The domain is consumer questions answered from public financial-regulator guidance: the
Financial Consumer Agency of Canada, and SEC investor bulletins. Public, regulated, nothing to
do with the employer, and the kind of content where an unsupported claim matters. That last
part is the point: a faithfulness judge tested on trivia is not tested at all.

**The text is committed, not the URL.** Regulator pages are rewritten without notice, and a
faithfulness judgement made against today's wording is meaningless a year later unless the
wording is kept. So each page is fetched once, reduced to a passage, and stored with the hash
of the bytes it came from and the date it was read. After that nothing here is ever called
again, exactly as `drift/sampling/fetch.py` is a development tool and not part of the record.

**This does not run on Peter's laptop.** Not because of a rule this time but because it does
not work: the work network's proxy makes an ordinary HTTPS read to canada.ca time out. It runs
in the `gold` workflow, like every other command here that touches the outside world.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from gate.gold import Publisher, SourceDoc, utc_now

USER_AGENT = "ai-release-gate/1 (gold set for judge calibration; one-off)"
TIMEOUT_S = 45

# A passage long enough to support two or three real questions and short enough that showing it
# to a judge 300 times, twice, costs cents rather than dollars. Cut at a paragraph boundary, so
# the labeller never has to judge faithfulness against half a sentence.
MAX_PASSAGE_CHARS = 2600
MIN_PASSAGE_CHARS = 400

# Everything inside these is furniture rather than content, and a judge shown a navigation menu
# will faithfully report that the document mentions "Skip to main content".
DROP_TAGS = frozenset(
    {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button"}
)
BLOCK_TAGS = frozenset(
    {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "div", "section", "article", "br"}
)

# The licences the two publishers put their material under. Recorded per document rather than
# assumed, because the gold set is committed and a reader is owed the terms it is under.
LICENCES: dict[Publisher, str] = {
    "fcac": "Open Government Licence - Canada",
    "sec": "United States government work, public domain",
}


class SourceSpec(BaseModel):
    """One page to fetch. `title` is what the labeller and the judge see above the passage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^(fcac|sec)-\d{3}$")
    publisher: Publisher
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")

    @property
    def licence(self) -> str:
        return LICENCES[self.publisher]


class _TextExtractor(HTMLParser):
    """HTML to plain text, keeping paragraph boundaries and dropping furniture.

    Deliberately small and stdlib-only. A full readability implementation would be better at
    finding the main column and would be another dependency and another thing to be wrong; the
    output of this one is committed and read by a human before any question is written from it,
    so a bad extraction is caught by the person writing the questions rather than by a library.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self.parts)


_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{2,}")
# The plain-punctuation rule (CLAUDE.md) applies to what this project writes, and a stored
# regulator page is quoted rather than written. Typographic characters are mapped anyway, so
# that the same passage reaches the model, the labeller and the judge as the same bytes
# whatever the publisher's style sheet did to an apostrophe.
# Built from code points rather than written out, exactly as drift/items.py builds its own
# table: a source file that contains a curly quote trips this project's lint rule against them.
TYPOGRAPHIC: dict[str, str] = {
    chr(0x2013): "-",  # en dash
    chr(0x2014): "-",  # em dash
    chr(0x2018): "'",  # left single quote
    chr(0x2019): "'",  # right single quote, how most publishers write an apostrophe
    chr(0x201C): '"',  # left double quote
    chr(0x201D): '"',  # right double quote
    chr(0x2026): "...",  # ellipsis
    chr(0x00A0): " ",  # no-break space
}


def to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.text
    for bad, good in TYPOGRAPHIC.items():
        text = text.replace(bad, good)
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(line for line in lines if line)).strip()


def passage(text: str, *, limit: int = MAX_PASSAGE_CHARS) -> str:
    """The first `limit` characters, cut at a paragraph boundary.

    Cut rather than summarised, because a summary would be this project writing the document
    it then measures faithfulness against, and every claim in it would be one step removed from
    something a regulator actually published.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n\n")
    if cut >= MIN_PASSAGE_CHARS:
        return head[:cut].strip()
    cut = head.rfind(". ")
    return (head[: cut + 1] if cut >= MIN_PASSAGE_CHARS else head).strip()


class FetchError(RuntimeError):
    """One page could not be read. Collected rather than raised, so one bad URL in a list of
    thirty costs a re-run of that one rather than the whole fetch."""


@dataclass(frozen=True, slots=True)
class Fetched:
    spec: SourceSpec
    document: SourceDoc | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.document is not None


Opener = Callable[[str], bytes]


def _open(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        if response.status != 200:
            raise FetchError(f"status {response.status}")
        body = response.read()
    return bytes(body)


def fetch_one(spec: SourceSpec, opener: Opener | None = None) -> Fetched:
    read = opener or _open
    try:
        body = read(spec.url)
    except (urllib.error.URLError, OSError, FetchError) as e:
        return Fetched(spec, None, f"{type(e).__name__}: {e}")
    text = passage(to_text(body.decode("utf-8", errors="replace")))
    if len(text) < MIN_PASSAGE_CHARS:
        return Fetched(
            spec,
            None,
            f"only {len(text)} characters of text after extraction, which is not a passage; "
            "check the URL points at a content page rather than an index",
        )
    return Fetched(
        spec,
        SourceDoc(
            id=spec.id,
            publisher=spec.publisher,
            title=spec.title,
            url=spec.url,
            retrieved_utc=utc_now(),
            bytes_sha256=hashlib.sha256(body).hexdigest(),
            text=text,
            licence=spec.licence,
        ),
        None,
    )


def fetch_all(
    specs: list[SourceSpec],
    *,
    opener: Opener | None = None,
    skip: set[str] | None = None,
) -> list[Fetched]:
    done = skip or set()
    return [fetch_one(s, opener) for s in specs if s.id not in done]


def load_specs(path: Path) -> list[SourceSpec]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    specs = [SourceSpec.model_validate(s) for s in raw.get("sources", [])]
    ids = {s.id for s in specs}
    if len(ids) != len(specs):
        raise ValueError("source ids must be unique")
    return specs

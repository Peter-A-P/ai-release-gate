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
import threading
import time
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

# `urllib`'s timeout is a SOCKET timeout, not a deadline. A host that dribbles bytes, or a
# chain of redirects each getting a fresh allowance, can hold a single fetch open far longer
# than this number suggests, and on 2026-09-20 a sixteen-page probe in CI ran past the twelve
# minutes its per-page timeouts implied. So there are three limits, not one: this per socket
# operation, `MAX_BYTES` on what is read, and `DEADLINE_S` across the whole list.
TIMEOUT_S = 20
# A regulator page is tens of kilobytes. Anything past this is not the page that was wanted,
# and reading it to the end to find that out is the slow way.
MAX_BYTES = 4_000_000
# The whole fetch, in seconds. Past it the remaining pages are reported as not attempted,
# which is a fact worth having rather than a job that hangs until the runner kills it.
DEADLINE_S = 300.0
# The hard wall-clock bound on ONE page, enforced by abandoning the thread doing the read
# rather than by asking it to stop. Generous against TIMEOUT_S because a legitimate fetch may
# be a connect, a redirect and a read, each entitled to its own socket allowance; tight enough
# that sixteen pages cannot outlast the deadline above by more than one page's worth.
PAGE_WALL_CLOCK_S = 75.0

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


# The element that holds the article, in the order they are looked for. Without this the first
# 2,500 characters of an investor.gov page are its cookie notice and its "Skip to main content"
# link, which is exactly what the first real fetch on 2026-09-20 stored: a passage nobody can
# write a question from, and one a judge would faithfully report as being about domain names.
MAIN_IDS = frozenset({"main-content", "main", "content", "block-system-main"})


class _TextExtractor(HTMLParser):
    """HTML to plain text, keeping paragraph boundaries and dropping furniture.

    Deliberately small and stdlib-only. A full readability implementation would be better at
    finding the main column and would be another dependency and another thing to be wrong; the
    output of this one is committed and read by a human before any question is written from it,
    so a bad extraction is caught by the person writing the questions rather than by a library.

    Text is collected twice: everything, and separately whatever sits inside the page's main
    region when it declares one (`<main>`, `role="main"`, or a familiar id). `text` prefers the
    main region whenever it is substantial, which is what keeps a site banner out of a passage.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip_depth = 0
        self._depth = 0
        self._main_depth = 0  # the depth the main region opened at, 0 when outside one

    @staticmethod
    def _is_main(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag == "main":
            return True
        found = {k.lower(): (v or "") for k, v in attrs}
        return found.get("role", "").lower() == "main" or found.get("id", "").lower() in MAIN_IDS

    def _emit(self, text: str) -> None:
        self.parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        if tag in DROP_TAGS:
            self._skip_depth += 1
            return
        # A main region already open wins: nesting one inside another would close the outer
        # early, on the inner one's end tag.
        if self._main_depth == 0 and self._skip_depth == 0 and self._is_main(tag, attrs):
            self._main_depth = self._depth
        if tag in BLOCK_TAGS and self._skip_depth == 0:
            self._emit("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<br/>` and friends: a block boundary that never closes, so it must not move depth.
        if tag in BLOCK_TAGS and self._skip_depth == 0:
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS and self._skip_depth == 0:
            self._emit("\n")
        if self._main_depth and self._depth <= self._main_depth:
            self._main_depth = 0
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._emit(data)

    @property
    def text(self) -> str:
        main = "".join(self.main_parts)
        # "Substantial" rather than "present": a page whose main region holds only a heading has
        # not told us where the article is, and the whole body is a better guess than a title.
        return main if len(main.strip()) >= MIN_PASSAGE_CHARS else "".join(self.parts)


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
        # One byte past the cap, so an oversized page is detected without reading it whole.
        body = response.read(MAX_BYTES + 1)
    return bytes(body)


def _read_with_wall_clock(
    read: Opener, url: str, *, wall_clock_s: float
) -> tuple[bytes | None, str | None]:
    """`read(url)`, abandoned if it has not finished in `wall_clock_s`.

    A socket timeout bounds one socket operation, not a fetch. A host that trickles a byte
    inside every allowance, or a redirect chain each hop of which gets a fresh one, runs
    indefinitely, and on 2026-09-20 a probe of sixteen pages did exactly that and had to be
    cancelled by hand after twenty-five minutes.

    There is no polite way to stop a thread blocked in a socket read, so it is abandoned: the
    worker is a daemon, the process is a short-lived command, and a leaked thread costs
    nothing next to a job that hangs until the runner kills it. `None, reason` is returned and
    the fetch moves to the next page.
    """
    out: list[tuple[bytes | None, str | None]] = []

    def work() -> None:
        try:
            out.append((read(url), None))
        except (urllib.error.URLError, OSError, FetchError) as e:
            out.append((None, f"{type(e).__name__}: {e}"))

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(wall_clock_s)
    if worker.is_alive():
        return None, (
            f"gave up after {wall_clock_s:.0f}s of wall clock; the host neither answered nor "
            "closed the connection"
        )
    return out[0] if out else (None, "the reader returned nothing")


def fetch_one(
    spec: SourceSpec,
    opener: Opener | None = None,
    *,
    wall_clock_s: float = PAGE_WALL_CLOCK_S,
) -> Fetched:
    read = opener or _open
    body, error = _read_with_wall_clock(read, spec.url, wall_clock_s=wall_clock_s)
    if body is None:
        return Fetched(spec, None, error)
    if len(body) > MAX_BYTES:
        return Fetched(
            spec, None, f"over {MAX_BYTES} bytes; this is not a page a question is written from"
        )
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
    deadline_s: float = DEADLINE_S,
    wall_clock_s: float = PAGE_WALL_CLOCK_S,
    clock: Callable[[], float] = time.monotonic,
) -> list[Fetched]:
    """Every page not already stored, until the deadline.

    The deadline exists because the per-page timeout is not one: see TIMEOUT_S. A page not
    reached is reported as not attempted rather than silently missing, so the next run knows
    the difference between "this URL is wrong" and "we ran out of time before asking".
    """
    done = skip or set()
    started = clock()
    out: list[Fetched] = []
    for spec in specs:
        if spec.id in done:
            continue
        if clock() - started >= deadline_s:
            out.append(Fetched(spec, None, f"not attempted: {deadline_s:.0f}s deadline reached"))
            continue
        out.append(fetch_one(spec, opener, wall_clock_s=wall_clock_s))
    return out


def load_specs(path: Path) -> list[SourceSpec]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    specs = [SourceSpec.model_validate(s) for s in raw.get("sources", [])]
    ids = {s.id for s in specs}
    if len(ids) != len(specs):
        raise ValueError("source ids must be unique")
    return specs

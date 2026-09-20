"""Turning a regulator's HTML into a passage, with no network anywhere in sight."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gate import sources
from gate.sources import SourceSpec, fetch_all, fetch_one, passage, to_text

SPECS = Path(__file__).resolve().parent.parent / "gate" / "specs"

PAGE = """<!doctype html>
<html><head><title>Refunds</title><style>p { color: red }</style>
<script>window.analytics = 1;</script></head>
<body>
<header><a href="#main">Skip to main content</a></header>
<nav><ul><li><a href="/a">Banking</a></li><li><a href="/b">Credit</a></li></ul></nav>
<main>
<h1>Credit card holds</h1>
<p>A hold on a credit card can last up to 30&nbsp;days.</p>
<p>You don&rsquo;t need to call the merchant &mdash; the hold expires on its own.</p>
<ul><li>Cheques under $1,500 are usually available the next business day.</li>
<li>Larger cheques can be held for up to 8 business days.</li></ul>
</main>
<footer><p>Date modified: 2026-01-01</p></footer>
</body></html>"""


def spec(
    n: int = 1, publisher: str = "fcac", url: str = "https://example.invalid/page"
) -> SourceSpec:
    return SourceSpec.model_validate(
        {"id": f"{publisher}-{n:03d}", "publisher": publisher, "title": "Credit cards", "url": url}
    )


def test_extraction_keeps_the_content_and_drops_the_furniture() -> None:
    text = to_text(PAGE)
    assert "A hold on a credit card can last up to 30 days." in text
    assert "Cheques under $1,500" in text
    assert "Credit card holds" in text
    for furniture in ("Skip to main content", "window.analytics", "color: red", "Date modified"):
        assert furniture not in text
    # Navigation link text is inside <nav> and goes with it.
    assert "Banking" not in text


def test_extraction_normalises_the_publisher_s_typography() -> None:
    """The same passage has to reach the model, the labeller and the judge as the same bytes,
    whatever a style sheet did to an apostrophe."""
    text = to_text(PAGE)
    assert "You don't need to call the merchant - the hold expires" in text
    for bad in (0x2019, 0x2014, 0x00A0, 0x201C, 0x2026):
        assert chr(bad) not in text


def test_list_items_and_paragraphs_stay_apart() -> None:
    text = to_text("<p>One.</p><ul><li>Two.</li><li>Three.</li></ul>")
    assert "One.\nTwo.\nThree." in text.replace("\n\n", "\n")


def test_a_passage_is_cut_at_a_paragraph_boundary_not_mid_sentence() -> None:
    body = "\n\n".join(f"Paragraph {n} says something checkable about fees." * 3 for n in range(40))
    cut = passage(body, limit=1200)
    assert len(cut) <= 1200
    assert cut.endswith(".")
    assert body.startswith(cut)
    assert "\n\n" in cut, "more than one paragraph survived"


def test_a_short_document_is_left_whole() -> None:
    assert passage("Short and complete.") == "Short and complete."


def test_a_passage_with_no_paragraph_break_falls_back_to_a_sentence_boundary() -> None:
    body = "A sentence about fees. " * 200
    cut = passage(body, limit=1000)
    assert cut.endswith(".") and len(cut) <= 1000


def test_a_page_that_yields_no_passage_is_a_failure_with_a_reason() -> None:
    """An index page is mostly links, and links live in nav. The fetcher refuses it rather
    than storing a document a question cannot be written from."""
    result = fetch_one(spec(), opener=lambda url, ua: b"<html><nav><a>Index</a></nav></html>")
    assert not result.ok and result.document is None
    assert result.error is not None and "not a passage" in result.error
    assert "index" in result.error, "the message says what to check"


def test_a_network_failure_is_collected_rather_than_raised() -> None:
    def boom(url: str, ua: str) -> bytes:
        raise TimeoutError("the read operation timed out")

    results = fetch_all([spec(1), spec(2)], opener=boom)
    assert len(results) == 2
    assert all(not r.ok for r in results)
    assert results[0].error is not None and "timed out" in results[0].error


def test_a_good_page_is_stored_with_its_hash_its_date_and_its_licence() -> None:
    body = PAGE.encode("utf-8") + b"<p>" + (b"More checkable detail about fees. " * 40) + b"</p>"
    result = fetch_one(spec(), opener=lambda url, ua: body)
    assert result.ok and result.document is not None
    doc = result.document
    assert doc.id == "fcac-001" and doc.publisher == "fcac"
    assert doc.licence == "Open Government Licence - Canada"
    assert len(doc.bytes_sha256) == 64
    assert doc.retrieved_utc.endswith("Z")
    assert "A hold on a credit card" in doc.text
    sec = fetch_one(spec(1, "sec"), opener=lambda url, ua: body)
    assert sec.document is not None and "public domain" in sec.document.licence


def test_already_fetched_pages_are_skipped() -> None:
    calls: list[str] = []

    def opener(url: str, ua: str) -> bytes:
        calls.append(url)
        return PAGE.encode("utf-8") + b"<p>" + (b"Detail about fees. " * 60) + b"</p>"

    fetch_all([spec(1), spec(2)], opener=opener, skip={"fcac-001"})
    assert len(calls) == 1, "a page already stored is never fetched twice"


def test_only_https_and_known_publishers_are_accepted() -> None:
    with pytest.raises(ValidationError):
        spec(url="http://example.invalid/insecure")
    with pytest.raises(ValidationError):
        SourceSpec.model_validate(
            {"id": "abc-001", "publisher": "abc", "title": "x", "url": "https://x.invalid"}
        )


def test_the_shipped_source_lists_load_and_are_internally_consistent() -> None:
    working = sources.load_specs(SPECS / "gold-sources.yaml")
    blocked = sources.load_specs(SPECS / "gold-sources-fcac.yaml")
    assert len(working) >= 10 and len(blocked) >= 10
    for specs in (working, blocked):
        assert len({s.id for s in specs}) == len(specs)
        for s in specs:
            assert s.id.startswith(s.publisher + "-"), f"{s.id} does not name its publisher"
            assert s.url.startswith("https://")
            assert s.licence
    # The ids must not collide across the two files, because both write into one sources.jsonl.
    assert not ({s.id for s in working} & {s.id for s in blocked})


def test_the_two_lists_are_split_by_what_can_actually_be_reached() -> None:
    """Measured 2026-09-20: every canada.ca page timed out from a GitHub runner and every
    investor.gov page answered. The split is kept so that probing the working list costs a
    minute instead of twelve spent on a tarpit."""
    working = sources.load_specs(SPECS / "gold-sources.yaml")
    blocked = sources.load_specs(SPECS / "gold-sources-fcac.yaml")
    assert {s.publisher for s in working} == {"sec"}
    assert {s.publisher for s in blocked} == {"fcac"}
    assert all("investor.gov" in s.url for s in working), (
        "www.sec.gov returns 403 to undeclared traffic and this project does not put a "
        "personal address in a User-Agent to get around it"
    )


def test_the_whole_fetch_has_a_deadline_because_the_per_page_timeout_is_not_one() -> None:
    """urllib's timeout is a socket timeout. A host that dribbles bytes, or a chain of
    redirects each getting a fresh allowance, runs past it; a sixteen-page probe in CI on
    2026-09-20 ran past the twelve minutes its per-page timeouts implied. Pages not reached
    are reported as not attempted, which is different from a URL being wrong."""
    now = [0.0]

    def slow(url: str, ua: str) -> bytes:
        now[0] += 60.0
        raise TimeoutError("dribbling")

    specs = [spec(n) for n in range(1, 7)]
    results = fetch_all(specs, opener=slow, deadline_s=180.0, clock=lambda: now[0])
    assert len(results) == 6
    attempted = [r for r in results if r.error is not None and "not attempted" not in r.error]
    not_attempted = [r for r in results if r.error is not None and "not attempted" in r.error]
    assert len(attempted) == 3 and len(not_attempted) == 3
    assert "180s deadline" in not_attempted[0].error  # type: ignore[operator]


def test_an_enormous_response_is_refused_rather_than_stored() -> None:
    """A regulator page is tens of kilobytes. Something far larger is not the page that was
    wanted, and the default opener stops reading one byte past the cap rather than pulling a
    hundred megabytes down to discover that."""
    huge = b"<p>" + b"x" * (sources.MAX_BYTES + 10) + b"</p>"
    result = fetch_one(spec(), opener=lambda url, ua: huge)
    assert not result.ok
    assert result.error is not None and "not a page a question is written from" in result.error


def test_a_page_that_never_answers_is_abandoned_rather_than_waited_on() -> None:
    """The failure that actually happened: a probe in CI sat on one page past every timeout it
    had and had to be cancelled by hand. A socket timeout bounds a socket operation, not a
    fetch, so the read is given a wall clock and abandoned when it runs out."""
    import threading as _threading

    release = _threading.Event()

    def never(url: str, ua: str) -> bytes:
        release.wait(30)  # the caller must not wait for this
        return b"too late"

    try:
        result = fetch_one(spec(), opener=never, wall_clock_s=0.2)
        assert not result.ok
        assert result.error is not None and "gave up after" in result.error
        assert "neither answered nor closed" in result.error
    finally:
        release.set()


def test_one_slow_page_does_not_eat_the_whole_list() -> None:
    import threading as _threading

    release = _threading.Event()
    reached: list[str] = []

    def one_slow(url: str, ua: str) -> bytes:
        reached.append(url)
        if len(reached) == 1:
            release.wait(30)
        return PAGE.encode("utf-8") + b"<p>" + (b"Detail about fees. " * 60) + b"</p>"

    try:
        results = fetch_all([spec(1), spec(2)], opener=one_slow, wall_clock_s=0.2)
        assert results[0].error is not None and "gave up after" in results[0].error
        assert results[1].ok, "the second page is still fetched"
    finally:
        release.set()


BANNERED = (
    "<html><body><a href='#main'>Skip to main content</a>"
    "<div class='usa-banner'><p>The .gov means it is official. "
    + ("Boilerplate about federal domain names. " * 30)
    + "</p></div>"
    "<main><h1>Mutual funds</h1><p>"
    + ("A mutual fund pools money from many investors. " * 30)
    + "</p></main></body></html>"
)


def test_the_page_s_main_region_wins_over_its_banner() -> None:
    """What the first real fetch got wrong. investor.gov puts its cookie notice in a plain
    div, so dropping nav, header and footer was not enough and the stored passage was 2,500
    characters of boilerplate about federal domain names: nothing a question can be written
    from, and something a judge would faithfully report the document as being about."""
    text = to_text(BANNERED)
    assert "A mutual fund pools money" in text
    assert "Boilerplate about federal domain names" not in text
    assert "Skip to main content" not in text
    assert text.startswith("Mutual funds")


def test_a_main_region_is_also_found_by_role_and_by_id() -> None:
    body = "<p>" + ("Real content about fees. " * 40) + "</p>"
    for opener, closer in (
        ("<div id='main-content'>", "</div>"),
        ("<div role='main'>", "</div>"),
        ("<section id='content'>", "</section>"),
    ):
        html = (
            f"<html><body><div><p>{'Banner. ' * 80}</p></div>{opener}{body}{closer}</body></html>"
        )
        text = to_text(html)
        assert "Real content about fees." in text
        assert "Banner." not in text, f"{opener} did not win"


def test_a_main_region_too_thin_to_be_the_article_falls_back_to_the_body() -> None:
    """A page whose main region holds only a heading has not told us where the article is,
    and the whole body is a better guess than a title."""
    html = (
        "<html><body><div><p>"
        + ("Something substantial in the body. " * 40)
        + "</p></div><main><h1>Only a heading</h1></main></body></html>"
    )
    assert "Something substantial" in to_text(html)


def test_a_void_block_tag_does_not_unbalance_the_depth_count() -> None:
    """`<br/>` never closes. Counting it as a level deep would close the main region on the
    next end tag and hand the banner back."""
    html = (
        "<html><body><main><p>First line.<br/>Second line.</p><p>"
        + ("More real content. " * 40)
        + "</p></main><div><p>"
        + ("Footer noise. " * 40)
        + "</p></div></body></html>"
    )
    text = to_text(html)
    assert "First line." in text and "Second line." in text and "More real content." in text
    assert "Footer noise." not in text


def test_invisible_characters_are_removed_because_they_defeat_a_literal_check() -> None:
    """A zero width space is not whitespace to `str.split`, so one sitting inside "$100" would
    silently defeat the check that a question's expected points are really in its passage.
    Three were in the first 49 documents fetched."""
    html = "<p>the first \u200b$100\u202fof funds\ufeff must be available</p>" + ("<p>x</p>" * 200)
    text = to_text(html)
    assert "the first $100 of funds must be available" in text
    for invisible in (0x200B, 0x202F, 0xFEFF, 0x200C, 0x2009):
        assert chr(invisible) not in text

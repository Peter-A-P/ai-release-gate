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
    result = fetch_one(spec(), opener=lambda url: b"<html><nav><a>Index</a></nav></html>")
    assert not result.ok and result.document is None
    assert result.error is not None and "not a passage" in result.error
    assert "index" in result.error, "the message says what to check"


def test_a_network_failure_is_collected_rather_than_raised() -> None:
    def boom(url: str) -> bytes:
        raise TimeoutError("the read operation timed out")

    results = fetch_all([spec(1), spec(2)], opener=boom)
    assert len(results) == 2
    assert all(not r.ok for r in results)
    assert results[0].error is not None and "timed out" in results[0].error


def test_a_good_page_is_stored_with_its_hash_its_date_and_its_licence() -> None:
    body = PAGE.encode("utf-8") + b"<p>" + (b"More checkable detail about fees. " * 40) + b"</p>"
    result = fetch_one(spec(), opener=lambda url: body)
    assert result.ok and result.document is not None
    doc = result.document
    assert doc.id == "fcac-001" and doc.publisher == "fcac"
    assert doc.licence == "Open Government Licence - Canada"
    assert len(doc.bytes_sha256) == 64
    assert doc.retrieved_utc.endswith("Z")
    assert "A hold on a credit card" in doc.text
    sec = fetch_one(spec(1, "sec"), opener=lambda url: body)
    assert sec.document is not None and "public domain" in sec.document.licence


def test_already_fetched_pages_are_skipped() -> None:
    calls: list[str] = []

    def opener(url: str) -> bytes:
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


def test_the_shipped_source_list_loads_and_is_internally_consistent() -> None:
    specs = sources.load_specs(SPECS / "gold-sources.yaml")
    assert len(specs) >= 10
    assert len({s.id for s in specs}) == len(specs)
    assert {s.publisher for s in specs} == {"fcac", "sec"}
    for s in specs:
        assert s.id.startswith(s.publisher + "-"), f"{s.id} does not name its publisher"
        assert s.url.startswith("https://")
        assert s.licence


def test_the_whole_fetch_has_a_deadline_because_the_per_page_timeout_is_not_one() -> None:
    """urllib's timeout is a socket timeout. A host that dribbles bytes, or a chain of
    redirects each getting a fresh allowance, runs past it; a sixteen-page probe in CI on
    2026-09-20 ran past the twelve minutes its per-page timeouts implied. Pages not reached
    are reported as not attempted, which is different from a URL being wrong."""
    now = [0.0]

    def slow(url: str) -> bytes:
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
    result = fetch_one(spec(), opener=lambda url: huge)
    assert not result.ok
    assert result.error is not None and "not a page a question is written from" in result.error

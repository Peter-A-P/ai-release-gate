"""Fetching the public sources once, into a cache that is never committed.

PLAN.md section 3: public benchmark items are sampled once with a recorded seed and then
frozen as files in the repository, and the loaders are never called again. So this module is
a development tool, not part of the monthly run: nothing here is imported by the runner.

Every fetch records the URL, the SHA-256 of the bytes and the date, which the manifest
carries (`drift/suite/v1/SOURCES.json`), so anyone can say exactly which bytes the suite was
drawn from. The cache lives under `.cache/sources/` (gitignored), which makes a re-run of the
sampler offline and therefore reproducible.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

USER_AGENT = "ai-release-gate-sampler/1 (drift suite v1, one-off sampling)"
HF_ROWS = "https://datasets-server.huggingface.co/rows"
HF_PAGE = 100  # the endpoint's maximum
PAUSE_S = 1.0  # between pages: the anonymous quota on the rows endpoint is tight
TIMEOUT_S = 60
# The free rows endpoint rate-limits a full-split walk, so this fetcher backs off and retries.
# That is not the runner's rule and does not weaken it: PLAN.md section 2.3 bans retries on
# *vendor* calls, where a 429 is part of the record. Here a 429 is only slow, and the sampled
# items are identical either way.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRIES = 8
BACKOFF_CAP_S = 120.0


class FetchError(RuntimeError):
    """A source could not be fetched. The sampler stops rather than sample a short pool."""


@dataclass(frozen=True, slots=True)
class Fetched:
    """Provenance for one fetched source: what was asked for, and which bytes came back."""

    name: str
    url: str
    sha256: str
    fetched: str  # ISO date, UTC
    rows_total: int

    def as_record(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "payload_sha256": self.sha256,
            "fetched": self.fetched,
            "rows_upstream": self.rows_total,
        }


@dataclass(frozen=True, slots=True)
class Row:
    """One upstream row with the index it has in its split: the item's provenance."""

    idx: int
    data: Mapping[str, Any]

    def text(self, key: str) -> str:
        v = self.data.get(key)
        return v if isinstance(v, str) else ""


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _cache_paths(cache: Path, url: str) -> tuple[Path, Path]:
    stem = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return cache / f"{stem}.body", cache / f"{stem}.meta.json"


def _retry_after(header: str | None, attempt: int) -> float:
    """The wait before the next attempt: the server's Retry-After when it gives one, else
    exponential backoff."""
    if header:
        try:
            return min(float(header.strip()), BACKOFF_CAP_S)
        except ValueError:
            pass
    return min(2.0**attempt, BACKOFF_CAP_S)


def _get(url: str) -> bytes:
    """The bytes at a URL, retrying a rate limit or a transient server error."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = ""
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code not in RETRY_STATUS or attempt == RETRIES - 1:
                raise FetchError(f"{url}: {last}") from e
            time.sleep(_retry_after(e.headers.get("Retry-After"), attempt))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            if attempt == RETRIES - 1:
                raise FetchError(f"{url}: {last}") from e
            time.sleep(_retry_after(None, attempt))
    raise FetchError(f"{url}: {last} after {RETRIES} attempts")


def fetch(url: str, cache: Path, *, refresh: bool = False) -> tuple[bytes, str]:
    """The bytes at a URL and the date they were fetched, through the cache.

    A cached body is returned unchanged; the recorded date stays the date of the first fetch,
    which is the date the suite was drawn from.
    """
    body_path, meta_path = _cache_paths(cache, url)
    if not refresh and body_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return body_path.read_bytes(), str(meta["fetched"])
    body = _get(url)
    fetched = _today()
    cache.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    meta_path.write_text(
        json.dumps({"url": url, "fetched": fetched}, indent=2) + "\n", encoding="utf-8"
    )
    return body, fetched


def hf_rows(
    name: str, dataset: str, config: str, split: str, cache: Path, *, refresh: bool = False
) -> tuple[tuple[Row, ...], Fetched]:
    """Every row of a Hugging Face split, page by page, with one provenance record.

    The rows endpoint is used rather than the `datasets` library so that sampling needs no
    heavy dependency and so the exact bytes behind each item can be hashed. Paging is by
    offset, which is stable for a given dataset revision; `rows_total` is recorded and a
    change in it between pages is an error rather than a silently short pool.
    """
    rows: list[Row] = []
    hasher = hashlib.sha256()
    first_url = ""
    fetched = ""
    total = -1
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": dataset,
                "config": config,
                "split": split,
                "offset": offset,
                "length": HF_PAGE,
            }
        )
        url = f"{HF_ROWS}?{query}"
        body, page_fetched = fetch(url, cache, refresh=refresh)
        hasher.update(body)
        if not first_url:
            first_url, fetched = url, page_fetched
        try:
            page: Any = json.loads(body)
        except ValueError as e:
            raise FetchError(f"{url}: response is not JSON") from e
        if not isinstance(page, dict) or "rows" not in page:
            raise FetchError(f"{url}: unexpected response {str(page)[:200]}")
        page_total = int(page.get("num_rows_total", -1))
        if total == -1:
            total = page_total
        elif page_total != total:
            raise FetchError(
                f"{dataset} {config}/{split}: row count changed mid-fetch "
                f"({total} then {page_total}); the dataset moved, so start again"
            )
        batch = page["rows"]
        if not isinstance(batch, list) or not batch:
            break
        for wrapper in batch:
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("row"), dict):
                raise FetchError(f"{url}: unexpected row {str(wrapper)[:200]}")
            rows.append(Row(idx=int(wrapper.get("row_idx", offset)), data=wrapper["row"]))
        offset += len(batch)
        if total >= 0 and offset >= total:
            break
        time.sleep(PAUSE_S)
    if total >= 0 and len(rows) != total:
        raise FetchError(f"{dataset} {config}/{split}: got {len(rows)} rows, expected {total}")
    return tuple(rows), Fetched(
        name=name,
        url=f"{HF_ROWS}?dataset={dataset}&config={config}&split={split}",
        sha256=hasher.hexdigest(),
        fetched=fetched,
        rows_total=len(rows),
    )


def csv_rows(
    name: str, url: str, cache: Path, *, refresh: bool = False
) -> tuple[tuple[Row, ...], Fetched]:
    """Every row of a CSV at a URL, in file order, with one provenance record."""
    body, fetched = fetch(url, cache, refresh=refresh)
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    rows = tuple(
        Row(idx=i, data={k: v for k, v in row.items() if k is not None})
        for i, row in enumerate(reader)
    )
    return rows, Fetched(
        name=name,
        url=url,
        sha256=hashlib.sha256(body).hexdigest(),
        fetched=fetched,
        rows_total=len(rows),
    )


def rows_from_records(records: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    """Rows straight from in-memory records: how the tests drive the builders offline."""
    return tuple(Row(idx=i, data=r) for i, r in enumerate(records))

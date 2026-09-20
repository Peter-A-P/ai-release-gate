# Where the gold set's documents come from, and what could not be reached

The judge calibration gold set needs 100 consumer questions answerable from public
financial-regulator guidance. PLAN.md B4 names two regulators: the Financial Consumer Agency of
Canada, and the SEC. This is what happened when the pages were actually fetched, because the
result changes the plan and the change should be visible rather than quietly absorbed.

## The measurement

`gate gold fetch`, sixteen URLs, from an `ubuntu-24.04` GitHub Actions runner on **2026-09-20**
(run `35522317109`). Plain `urllib`, one request each, a `User-Agent` that names the project.

| Host | Result |
|---|---|
| `www.investor.gov` | **4 of 5 fetched**, 1,578 to 2,540 characters of text each |
| `www.sec.gov` | **403 Forbidden** |
| `www.canada.ca` | **0 of 10. Every one timed out**, identically |

The single investor.gov failure was a 404 on a path guessed wrongly, which is an ordinary
mistake and was corrected.

## canada.ca does not answer

Ten for ten, the same error: `TimeoutError: The read operation timed out`. Not a 403, not a
404, not a redirect. The host accepts the connection and then says nothing, which is what a web
application firewall does to traffic it has decided not to serve. Ten out of ten means it is
the host and not the paths.

The same read also times out from Peter's laptop on the work network, which has a TLS
inspecting proxy. So from here the two cannot be told apart: it may be canada.ca refusing
data-centre addresses, it may be the proxy, it may be both. What is certain is that the CI
route does not work.

**This project does not work around it by pretending to be a browser.** A publisher that has
put up a block has made a decision, and evading it to collect a hundred questions is not a
trade this project makes. The same reasoning appears in Part A, where a classifier is never
tuned until every vendor looks safe.

Three ways forward, none of them chosen:

1. **Fetch the Canadian half from a home connection.** One command, and the result is committed
   like any other document:
   `uv run gate gold fetch --list gate/specs/gold-sources-fcac.yaml --i-am-allowed-to-reach-the-internet`.
   Cheapest option if it works, and it tells us which of the two blocks we are looking at.
2. **Drop the Canadian half.** The gold set becomes SEC-only. It is still public, still
   regulated, still the kind of content where an unsupported claim matters, which is what B4
   asked the domain for. It is a change to the plan and so is Peter's call.
3. **Ask FCAC for the content another way.** Slow, and out of proportion to a calibration set.

Until one is chosen, `gate/specs/gold-sources-fcac.yaml` holds the Canadian entries, separate
from the working list so that probing the working list costs a minute rather than twelve spent
on a tarpit. The file is kept rather than deleted: a public government page being unreachable
from ordinary infrastructure is a fact worth keeping.

## www.sec.gov asks traffic to identify itself

`www.sec.gov` returns 403 to requests whose `User-Agent` does not carry a contact address. That
is the SEC's stated expectation of automated traffic and it is a reasonable one.

The only address available here is Peter's employer's, and **this project does not put a
personal or work address into a request header to an unrelated service**. So `www.sec.gov` is
left alone.

`investor.gov` is the SEC's own investor education site, answers ordinary requests, and carries
exactly the material B4 wanted from "SEC investor bulletins". The American half of the gold set
comes from there. If a contact address Peter is happy to publish ever exists, `www.sec.gov`
opens up and can be added; the fetcher needs one line changed.

## Why the text is committed and not the URL

Every document is stored as a passage, with the SHA-256 of the bytes it came from and the date
it was read. Regulator pages are rewritten without notice. A faithfulness judgement made against
today's wording is meaningless a year later unless today's wording is kept, and a label that
cannot be checked against what the labeller actually read is not evidence.

The passage is **cut at a paragraph boundary, never summarised**. A summary would be this
project writing the document it then measures faithfulness against, and every claim in it would
be one step removed from something a regulator published.

Both sources allow it. investor.gov material is a United States government work and in the
public domain; the FCAC pages, if they are ever fetched, are under the Open Government Licence
- Canada. The licence is recorded per document rather than assumed.

## One bug this found

The probe ran for twenty-five minutes and had to be cancelled by hand, although its per-page
timeouts implied twelve. `urllib`'s timeout bounds a socket operation, not a fetch: a host that
trickles a byte inside every allowance, or a redirect chain each hop of which gets a fresh one,
runs indefinitely.

There are three limits now: twenty seconds per socket operation, four megabytes on what is
read, and five minutes across the whole list, with each page additionally abandoned after
seventy-five seconds of wall clock by walking away from the thread doing the read. A page the
deadline stops us reaching is reported as **not attempted**, which is a different fact from a
URL being wrong, and the next run needs to be able to tell them apart.

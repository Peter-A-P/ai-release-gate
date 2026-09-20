# Where the gold set's documents come from

The judge calibration gold set needs 100 consumer questions answerable from public
financial-regulator guidance. PLAN.md B4 names two regulators: the Financial Consumer Agency of
Canada, and the SEC. Both are in, 49 documents between them.

Getting there took three attempts and produced one finding worth publishing, because the
obvious reading of the first attempt was wrong.

## The finding: two public regulators want opposite things in a User-Agent

Measured 2026-09-20, every other variable held fixed.

| Host | `ai-release-gate/1 (gold set for judge calibration; one-off)` | `ai-release-gate/1 (+https://github.com/Peter-A-P/ai-release-gate)` | `curl/8.5.0` | no header |
|---|---|---|---|---|
| `www.canada.ca` | **timeout** | **200** | 200 | - |
| `www.investor.gov` | **200** | **403** | 403 | 200 |

`www.canada.ca` serves the conventional crawler form, a product token plus a `(+URL)` saying
who is asking, and **tarpits** everything else: it accepts the connection and never sends
anything, which surfaces as a read timeout rather than as a refusal. `www.investor.gov` is the
exact reverse and returns 403 to any User-Agent carrying a URL.

There is no single string that reaches both, so the User-Agent belongs to the source list
rather than to the fetcher, and each list carries its own with the reason beside it.

**None of this is a disguise.** Both forms name the project, and one of them links to its
public repository so that an administrator looking at a log can see exactly what is fetching
them and why. Claiming to be a browser is what is never done, and it is not done here: the
winning string on canada.ca is more identifying than the one that failed, not less.

## What the first attempt looked like, and why it was wrong

The first probe ran from a GitHub Actions runner. All ten canada.ca pages timed out,
identically, while investor.gov answered. The natural reading, and the one written down at the
time, was that canada.ca refuses data-centre addresses.

It was the User-Agent. The same string times out from an ordinary home connection, and the
conventional form succeeds from that same connection in two seconds. The location never
mattered.

Worth keeping as a reminder: ten identical failures from one environment looked like strong
evidence about that environment, and the variable that actually differed was in the request all
along. The way it was settled was the only way available, which was to change one thing at a
time.

## The second mistake: a section index is not a document

The first canada.ca pages to fetch successfully were section indexes, and they extracted
cleanly. `/services/banking.html` yields "Services and information" and then a list of link
descriptions. Perfectly good text, and useless here: a faithfulness question needs a passage
with something checkable in it, and a hub page has no claims to be unfaithful about.

The leaves were then discovered by reading the links out of each index rather than guessed, and
those carry what was wanted. From `banking/cashing-cheques.html`:

> Financial institutions must make the first $100 of all funds you deposit by cheque available
> to you right away.

That is a claim a model can get wrong in an interesting way, which is the whole point.

A related softer line: `gate gold status` names any passage under 900 characters. The fetcher
already refuses anything under 400 as an index page; between the two sits the glossary stub,
which fetches perfectly and makes a poor question because there is barely anything in it to be
unfaithful to. Four were dropped on that basis.

## www.sec.gov asks traffic to identify itself by email

`www.sec.gov` returns 403 to both forms. It asks automated traffic for a contact address, which
is a reasonable thing for it to ask.

The only address available here is Peter's employer's, and **this project does not put a
personal or work address into a request header to an unrelated service**. So `www.sec.gov` is
left alone.

`investor.gov` is the SEC's own investor education site, answers ordinary requests, and carries
exactly the material B4 wanted from "SEC investor bulletins". The American half comes from
there. If a contact address Peter is happy to publish ever exists, `www.sec.gov` opens up, and
the source list already has a field for it.

## What is stored

49 documents: 27 from investor.gov, 22 from FCAC. Median passage about 2,100 characters.

Each is stored as a passage with the SHA-256 of the bytes it came from and the date it was
read, and **the text is committed, not the URL**. Regulator pages are rewritten without notice.
A faithfulness judgement made against today's wording is meaningless a year later unless
today's wording is kept, and a label that cannot be checked against what the labeller actually
read is not evidence.

The passage is **cut at a paragraph boundary, never summarised**. A summary would be this
project writing the document it then measures faithfulness against, and every claim in it would
be one step removed from something a regulator published.

Licences are recorded per document rather than assumed: investor.gov material is a United
States government work in the public domain, FCAC pages are under the Open Government Licence
- Canada.

## Two bugs this found

**A socket timeout is not a deadline.** The first probe ran twenty-five minutes and had to be
cancelled by hand, although its per-page timeouts implied twelve. `urllib`'s timeout bounds one
socket operation; a host that trickles a byte inside every allowance runs forever. There are
four limits now: twenty seconds per socket operation, four megabytes on what is read, seventy-
five seconds of wall clock per page enforced by walking away from the thread doing the read,
and five minutes across the whole list. A page the deadline stops us reaching is reported as
**not attempted**, which is a different fact from a URL being wrong.

**The banner is not the document.** The first four investor.gov passages were 2,500 characters
of "Skip to main content. The .gov means it's official." Dropping `nav`, `header` and `footer`
was not enough, because the notice sits in an ordinary `div`. The extractor now prefers the
page's main region when it declares one, by `<main>`, by `role="main"`, or by a familiar id,
and falls back to the whole body when that region is too thin to be the article.

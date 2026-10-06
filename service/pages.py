"""The pages: plain server-rendered HTML, no JavaScript and no build step (PLAN.md B3, B8).

Every figure is formatted by the library's own `Estimate.compact`, the function that writes the
README table, so a number reads identically on a page, in a report and in the README.

The look is peterparker.ca's, as the other projects' public pages are (01, 02, 08, 12): its
palette, its two typefaces and the 3px rule over the page, so a visitor arriving from the
portfolio does not land on a different-looking site. The fonts are served from this site
(`service/static/fonts/`), never linked from another host: a font is an off-origin request like
any other. The charts are HTML rather than SVG, positioned in percentages, so their labels stay
the size of the text around them on a phone instead of shrinking with a viewBox.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Sequence
from html import escape

from drift.analysis.metrics import ArmMetrics, drift_declared, month_over_month
from drift.analysis.report import ClassifierCheck, join_and
from drift.analysis.stats import Estimate
from gate.aa import AAStudy
from gate.judge import calibration as calib
from gate.ledger import GateRecord
from gate.redteam.suite import FAILURE, SUITES
from service.readmodel import ReadModel, Run

REPO = "https://github.com/Peter-A-P/ai-release-gate"
PORTFOLIO = "https://peterparker.ca"
PROJECT_PAGE = "https://peterparker.ca/projects/ai-release-gate/"

NAV = (
    ("/", "Overview"),
    ("/drift", "Drift record"),
    ("/costs", "Cost"),
    ("/gate", "Gate decisions"),
    ("/judge", "Judge calibration"),
    ("/redteam", "Red team"),
)

CSS = """
@font-face { font-family: "Newsreader"; font-style: normal; font-weight: 200 800;
  font-display: swap; src: url(/fonts/newsreader-latin.woff2) format("woff2"); }
@font-face { font-family: "Inter"; font-style: normal; font-weight: 400 600;
  font-display: swap; src: url(/fonts/inter-latin.woff2) format("woff2"); }
:root {
  color-scheme: light dark;
  --paper: #f5f3ee; --paper-soft: #fdfcf9; --ink: #16181d; --ink-soft: #3c4048;
  --ink-faint: #6b7079; --line: #e3dfd6; --line-2: #cfc9bd; --line-soft: #eeebe4;
  --accent: #0f5c6e; --accent-ink: #0b4653; --accent-soft: #e4eff1;
  --warn: #c0392b; --good: #1e7a4c; --amber: #9a6700; --sim: #6d3f9e;
  --s1: #0f5c6e; --s2: #6d3f9e; --s3: #9a6700; --s4: #1e7a4c;
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
  --sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace;
  --radius: 10px; --shadow: 0 6px 24px -18px rgba(0, 0, 0, 0.35); --column: 66rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #0e1013; --paper-soft: #15181d; --ink: #ece9e2; --ink-soft: #c9c6bf;
    --ink-faint: #969ba5; --line: #262a31; --line-2: #363b44; --line-soft: #1c2026;
    --accent: #7cc7d6; --accent-ink: #a9dde7; --accent-soft: #14262b;
    --warn: #f0736a; --good: #58c286; --amber: #e0b35a; --sim: #b191e0;
    --s1: #7cc7d6; --s2: #b191e0; --s3: #e0b35a; --s4: #58c286;
    --shadow: 0 6px 24px -14px rgba(0, 0, 0, 0.6);
  }
}
* { box-sizing: border-box; }
html { font-size: 18px; -webkit-text-size-adjust: 100%; }
body { overflow-x: clip; margin: 0; background: var(--paper); color: var(--ink); font-family: var(--sans);
  font-size: 1rem; line-height: 1.72; border-top: 3px solid var(--accent);
  font-feature-settings: "cv11", "ss01"; }
main { max-width: var(--column); margin: 0 auto; padding: 0 1.5rem 4rem; }
a { color: var(--accent); text-decoration: none; text-underline-offset: 0.15em; }
a:hover, a:focus-visible { text-decoration: underline; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
code { font-family: var(--mono); font-size: 0.86em; }
h1, h2, h3 { font-family: var(--serif); font-weight: 500; letter-spacing: -0.012em; }
h1 { font-size: clamp(2.1rem, 4.6vw, 3rem); line-height: 1.1; margin: 0 0 1rem; }
h2 { font-size: clamp(1.55rem, 2.6vw, 2rem); line-height: 1.2; margin: 0 0 0.7rem; }
h3 { font-size: 1.2rem; line-height: 1.25; margin: 0 0 0.45rem; }
p, li { margin: 0 0 0.85rem; }
.muted { color: var(--ink-faint); }
.pass { color: var(--good); font-weight: 600; }
.block { color: var(--warn); font-weight: 600; }
.warn { color: var(--amber); font-weight: 600; }

.top { border-bottom: 1px solid var(--line); }
.top-inner { max-width: var(--column); margin: 0 auto; padding: 0 1.5rem; height: 4rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.brand { display: inline-flex; align-items: center; gap: 0.7rem; color: var(--ink);
  font-weight: 600; letter-spacing: -0.01em; }
.brand:hover { text-decoration: none; color: var(--accent-ink); }
.mono-mark { width: 1.9rem; height: 1.9rem; border-radius: 6px; background: var(--accent);
  color: #fdfcf9; font-family: var(--serif); font-weight: 500; font-size: 1.15rem;
  display: inline-flex; align-items: center; justify-content: center; }
@media (prefers-color-scheme: dark) { .mono-mark { color: #0e1013; } }
.top-nav { font-size: 0.92rem; margin: 0; text-align: right; }
.top-nav a { color: var(--ink-soft); }
.tabs { border-bottom: 1px solid var(--line); background: var(--paper-soft); }
.tabs-inner { max-width: var(--column); margin: 0 auto; padding: 0.55rem 1.5rem;
  display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tabs a { font-size: 0.85rem; padding: 0.2rem 0.75rem; border-radius: 999px;
  border: 1px solid transparent; color: var(--ink-soft); }
.tabs a:hover { text-decoration: none; border-color: var(--line-2); color: var(--accent-ink); }
.tabs a[aria-current] { border-color: var(--accent); background: var(--accent-soft);
  color: var(--ink); font-weight: 600; }

.hero { position: relative; padding: 3.25rem 0 2.25rem; border-bottom: 1px solid var(--line); }
/* A wash of the accent behind the first screen, full width, fading into the page: the one place
   colour is used for its own sake, so the opening is not black on white alone. */
.hero::before { content: ""; position: absolute; z-index: -1; top: 0; bottom: 0; left: 50%;
  width: 100vw; margin-left: -50vw;
  background: radial-gradient(60rem 22rem at 85% 0%,
      color-mix(in srgb, var(--sim) 14%, transparent), transparent 70%),
    linear-gradient(180deg, var(--accent-soft), var(--paper) 85%); }
.hero h1 .hl { color: var(--accent); }
.hero .eyebrow { color: var(--accent-ink); }
.hero .point { border-top: 3px solid var(--accent); box-shadow: var(--shadow); }
.hero .point.good { border-top-color: var(--good); }
.hero .point.violet { border-top-color: var(--sim); }
.point .point-figure { color: var(--accent-ink); }
.point.good .point-figure { color: var(--good); }
.point.violet .point-figure { color: var(--sim); }
.eyebrow { text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.72rem;
  font-weight: 600; color: var(--ink-faint); margin: 0 0 0.6rem; }
.lead { font-size: 1.05rem; color: var(--ink-soft); }
.hero-points { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.9rem; margin: 1.75rem 0 1.1rem; }
.point, .stat, .takeaway, .card { background: var(--paper-soft); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 1rem 1.1rem; min-width: 0; }
.point-figure, .figure { display: block; font-family: var(--serif); font-size: 1.9rem;
  font-weight: 500; font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
  line-height: 1.15; }
.point-unit { display: block; margin-top: 0.2rem; font-size: 0.84rem; font-weight: 600;
  color: var(--ink-soft); line-height: 1.35; }
.point-label, .caption { display: block; margin-top: 0.4rem; padding-top: 0.4rem;
  border-top: 1px solid var(--line); font-size: 0.82rem; color: var(--ink-faint);
  line-height: 1.45; }
.hero-note, .note { font-size: 0.86rem; color: var(--ink-faint); }
.hero-note { margin: 0; }

.section { padding: 2.75rem 0; border-bottom: 1px solid var(--line); }
.section-lead { color: var(--ink-soft); }
.section > h3 { margin-top: 2rem; }
.part { padding: 2.75rem 0 0.5rem; }
.part h2 { font-size: clamp(1.8rem, 3.4vw, 2.4rem); }
.detail h1 { font-size: clamp(1.9rem, 3.8vw, 2.5rem); margin-top: 2.25rem; }
.detail h2 { font-size: 1.35rem; margin: 2.2rem 0 0.6rem; }
.detail > p { color: var(--ink-soft); }
.detail .note, .verdict { margin: 1.1rem 0 0; padding: 0.9rem 1.1rem;
  border-radius: 0 var(--radius) var(--radius) 0; background: var(--accent-soft);
  border-left: 3px solid var(--accent); font-size: 0.93rem; color: var(--ink); }
.verdict.good { background: color-mix(in srgb, var(--good) 12%, transparent);
  border-left-color: var(--good); }
.verdict.bad { background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-left-color: var(--warn); }

.scroll, .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 0.8rem 0 1rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem;
  font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--line);
  white-space: nowrap; vertical-align: top; }
th { font-weight: 600; font-size: 0.8rem; background: var(--line-soft);
  border-bottom-color: var(--line-2); }
td.wrap { white-space: normal; min-width: 18rem; }
table.idea td { white-space: normal; }
table.idea td:first-child { width: 34%; }
table.idea tr.real { background: color-mix(in srgb, var(--accent) 9%, transparent); }
@media (max-width: 46rem) {
  table.idea thead { display: none; }
  table.idea tr { display: block; padding: 0.6rem 0.2rem; border-bottom: 1px solid var(--line); }
  table.idea td { display: block; width: auto !important; border: 0; padding: 0.1rem 0.55rem; }
  table.idea td[data-label]::before { content: attr(data-label) ": "; color: var(--ink-faint); }
}

.legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 1rem 0 0.6rem;
  font-size: 0.82rem; color: var(--ink-soft); }
.key { display: inline-flex; align-items: center; gap: 0.45rem; }
.sw { display: inline-block; flex: none; }
.sw.bar { width: 18px; height: 10px; border-radius: 0 4px 4px 0;
  background: color-mix(in srgb, var(--accent) 30%, transparent);
  border-right: 2px solid var(--accent); }
.sw.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--sim); }
.sw.good { width: 10px; height: 10px; border-radius: 50%; background: var(--good); }
.sw.bad { width: 10px; height: 10px; border-radius: 50%; background: var(--warn); }
.sw.ci { width: 18px; height: 2px; background: var(--ink-faint); }
.sw.line { width: 2px; height: 14px; background: var(--ink-soft); }

.dp { margin: 0.4rem 0 0.4rem; }
.dp-group { font-size: 0.78rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink-faint); margin: 1rem 0 0.2rem; }
.dp-row { display: grid; grid-template-columns: 13rem 1fr 13.5rem; gap: 0 1rem;
  align-items: center; padding: 0.3rem 0; border-bottom: 1px solid var(--line-soft); }
.dp-label { font-size: 0.85rem; overflow-wrap: anywhere; line-height: 1.3; }
.dp-label small { display: block; color: var(--ink-faint); font-size: 0.75rem; }
.dp-track { position: relative; height: 1.9rem; }
.dp-grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--line); }
.dp-grid.zero { background: var(--line-2); }
.dp-value { font-size: 0.8rem; color: var(--ink-soft); line-height: 1.35;
  font-variant-numeric: tabular-nums; }
.dp-value b { color: var(--ink); font-weight: 600; }
.dp-bar { position: absolute; left: 0; top: 0.35rem; height: 0.7rem; border-radius: 0 4px 4px 0;
  background: color-mix(in srgb, var(--accent) 30%, transparent);
  border-right: 2px solid var(--accent); }
.dp-ci { position: absolute; height: 2px; background: var(--ink-faint); }
.dp-ci.upper { top: 0.67rem; }
.dp-ci.lower { top: 1.42rem; }
.dp-ci.mid { top: 0.9rem; }
.dp-dot { position: absolute; width: 10px; height: 10px; margin-left: -5px; border-radius: 50%;
  background: var(--sim); box-shadow: 0 0 0 2px var(--paper); }
.dp-dot.lower { top: 1.07rem; }
.dp-dot.mid { top: 0.55rem; }
.dp-dot.good { background: var(--good); }
.dp-dot.bad { background: var(--warn); }
.dp-rule { position: absolute; top: -0.2rem; bottom: -0.2rem; width: 2px; margin-left: -1px;
  background: var(--ink-soft); opacity: 0.6; }
.dp-axis { display: grid; grid-template-columns: 13rem 1fr 13.5rem; gap: 0 1rem; }
.dp-ticks { position: relative; height: 1.4rem; font-size: 0.72rem; color: var(--ink-faint); }
.dp-ticks span { position: absolute; transform: translateX(-50%); top: 0.2rem; white-space: nowrap; }
.dp-ticks span:first-child { transform: none; }
.dp-ticks span:last-child { transform: translateX(-100%); }
.dp-axis-title { grid-column: 2; font-size: 0.75rem; color: var(--ink-faint); margin: 0; }

.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.25rem 0; }
.arena { border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: var(--radius); padding: 1.1rem 1.25rem; background: var(--paper-soft);
  box-shadow: var(--shadow); min-width: 0; }
.arena.naive { border-left-color: var(--line-2); }
.arena h3 { font-size: 1.1rem; }
.arena .figure { margin: 0.4rem 0 0.1rem; }
.waffle { display: grid; grid-template-columns: repeat(32, 1fr); gap: 2px; margin: 0.8rem 0 0.4rem; }
.waffle span { aspect-ratio: 1; border-radius: 2px; background: var(--line); }
.waffle span.on { background: var(--warn); }
.tag { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
  padding: 0.12rem 0.55rem; border-radius: 999px; background: var(--line-soft);
  border: 1px solid var(--line); color: var(--ink-soft); white-space: nowrap; }
.tag.good { background: color-mix(in srgb, var(--good) 15%, transparent); color: var(--good);
  border-color: transparent; }
.tag.bad { background: color-mix(in srgb, var(--warn) 15%, transparent); color: var(--warn);
  border-color: transparent; }

table.heat td.cell { font-weight: 600; text-align: right; }
table.heat th.num { text-align: right; }
td.r0 { background: transparent; }
td.r1 { background: color-mix(in srgb, var(--warn) 9%, transparent); }
td.r2 { background: color-mix(in srgb, var(--warn) 18%, transparent); }
td.r3 { background: color-mix(in srgb, var(--warn) 30%, transparent); }
td.r4 { background: color-mix(in srgb, var(--warn) 44%, transparent); }

.steps { list-style: none; padding: 0; margin: 1.25rem 0; display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 0.9rem; counter-reset: step; }
.steps li { counter-increment: step; background: var(--paper-soft); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 1rem 1.1rem; margin: 0; font-size: 0.9rem;
  color: var(--ink-soft); }
.steps li::before { content: counter(step); display: inline-flex; width: 1.6rem; height: 1.6rem;
  border-radius: 50%; background: var(--accent); color: var(--paper-soft); font-weight: 600;
  font-size: 0.8rem; align-items: center; justify-content: center; margin-bottom: 0.5rem; }
.steps strong { display: block; color: var(--ink); font-size: 0.95rem; margin-bottom: 0.2rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.6rem 0 0; padding: 0;
  list-style: none; }
.chips li { font-size: 0.8rem; padding: 0.2rem 0.7rem; border: 1px solid var(--line-2);
  border-radius: 999px; background: var(--paper-soft); color: var(--ink-soft); margin: 0; }
.takeaways, .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1.1rem; }
.cards { grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); }
.takeaway p, .card p { font-size: 0.9rem; color: var(--ink-soft); margin: 0; }
.card h3 { font-size: 1.1rem; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: 1.25rem 0; }

svg text { fill: var(--ink-faint); font-size: 12px; }
svg .axis { stroke: var(--line); }
footer { max-width: var(--column); margin: 0 auto; padding: 2rem 1.5rem 3rem;
  font-size: 0.86rem; color: var(--ink-faint); border-top: 1px solid var(--line); }
footer .footer-lead { color: var(--ink); font-weight: 600; font-size: 0.95rem; }

@media (max-width: 58rem) {
  .compare, .split { grid-template-columns: 1fr; }
  .dp-row, .dp-axis { grid-template-columns: 9.5rem 1fr; }
  .dp-value { grid-column: 2; padding-bottom: 0.2rem; }
}
@media (max-width: 46rem) {
  html { font-size: 17px; }
  .takeaways { grid-template-columns: 1fr; }
  .top-inner { height: auto; padding: 0.8rem 1rem; }
  .top-nav { display: none; }
  .tabs-inner { padding: 0.5rem 1rem; }
  main { padding: 0 1rem 3rem; }
  footer { padding: 2rem 1rem 3rem; }
  .hero { padding: 2.25rem 0 1.75rem; }
  .section { padding: 2rem 0; }
  .dp-row, .dp-axis { grid-template-columns: 1fr; }
  .dp-label, .dp-value, .dp-axis-title, .dp-ticks { grid-column: 1; }
  .dp-axis > div:first-child, .dp-axis > div:last-child { display: none; }
  th, td { padding: 0.45rem 0.55rem; }
}
"""


def e(text: object) -> str:
    return escape(str(text), quote=True)


def page(model: ReadModel, path: str, title: str, body: str) -> str:
    nav = "".join(
        f'<a href="{href}"{" aria-current=page" if href == path else ""}>{e(label)}</a>'
        for href, label in NAV
    )
    commit = model.commit[:12] if model.commit else "unknown"
    full_title = (
        "AI Release Gate: did the AI get worse, or is that just noise?"
        if path == "/"
        else f"{title} | AI Release Gate"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="A release gate for AI: a frozen test asked of eight model configurations every month, five times each, so a change in score can be told apart from noise. Every number is reproducible from the repository.">
<style>{CSS}</style>
</head>
<body>
<header class="top"><div class="top-inner">
<a class="brand" href="{PORTFOLIO}"><span class="mono-mark" aria-hidden="true">P</span>Peter Parker</a>
<p class="top-nav"><a href="{PROJECT_PAGE}">Project 03: AI Release Gate</a></p>
</div></header>
<nav class="tabs" aria-label="This site"><div class="tabs-inner">{nav}</div></nav>
<main{' class="detail"' if path != "/" else ""}>
{body}
</main>
<footer>
<p class="footer-lead">Every number on this site is reproducible from the repository, offline, without a vendor key.</p>
<p><a href="{REPO}">The repository, the method and the reports</a> &middot;
<a href="{PROJECT_PAGE}">The project page</a> &middot;
<a href="{PORTFOLIO}">The rest of the portfolio</a></p>
<p>Read-only. Built {e(model.built_utc)} from commit <code>{e(commit)}</code>, by the same code
that writes the reports. Intervals are 95%.</p>
</footer>
</body>
</html>
"""


def table(headers: Sequence[str], rows: Iterable[Sequence[str]], *, wrap: int | None = None) -> str:
    """A table from already-escaped cells. `wrap` names the one column allowed to wrap."""
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="wrap">{c}</td>' if i == wrap else f"<td>{c}</td>"
            for i, c in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def est(x: Estimate, *, pct: bool = True) -> str:
    return e(x.compact(pct))


# ---------------------------------------------------------------------------- overview
#
# The front page, written for two readers at once: someone who has never heard of a noise floor
# and wants to know what this is for, and someone who will check the statistics. Each section
# says the plain thing first and puts the number that backs it beside it. Every figure is a
# library value from the read model, formatted by `Estimate.compact`; the words around a figure
# are fixed and the figure is not, so a new month changes the numbers and never the claim's
# wording into something the numbers do not say.


def _pct(v: float, lo: float, hi: float) -> float:
    """Where `v` sits on a track from `lo` to `hi`, in percent, clamped to the track."""
    if math.isnan(v) or hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))


def _ci(x: Estimate, lo: float, hi: float, where: str) -> str:
    if math.isnan(x.lo) or math.isnan(x.hi):
        return ""
    a, b = _pct(x.lo, lo, hi), _pct(x.hi, lo, hi)
    return f'<span class="dp-ci {where}" style="left:{a:.2f}%;width:{max(b - a, 0.4):.2f}%"></span>'


def _grid(lo: float, hi: float, values: Iterable[float]) -> str:
    return "".join(
        f'<span class="dp-grid{" zero" if v == 0 else ""}" style="left:{_pct(v, lo, hi):.2f}%"></span>'
        for v in values
    )


def _ticks(lo: float, hi: float, labels: Sequence[tuple[float, str]], title: str) -> str:
    spans = "".join(
        f'<span style="left:{_pct(v, lo, hi):.2f}%">{e(text)}</span>' for v, text in labels
    )
    return (
        f'<div class="dp-axis"><div></div><div class="dp-ticks">{spans}</div><div></div></div>'
        f'<div class="dp-axis"><div></div><p class="dp-axis-title">{e(title)}</p><div></div></div>'
    )


def _scale_top(values: Iterable[float], step: float) -> float:
    top = max((v for v in values if not math.isnan(v)), default=step)
    return max(step, math.ceil(top / step) * step)


def floor_chart(prev: Run | None, cur: Run, control: str | None) -> str:
    """Per model configuration: the same-day noise floor of the latest run as a bar with its
    interval, and the change since the run before as a dot with its interval. A dot inside the
    bar's reach is a move noise explains."""
    control_mom = None
    if prev is not None and control and control in prev.arms and control in cur.arms:
        control_mom = month_over_month(prev.arms[control], cur.arms[control])
    rows: list[tuple[str, ArmMetrics, Estimate | None, bool]] = []
    for key, m in cur.arms.items():
        if prev is not None and key in prev.arms:
            mom = month_over_month(prev.arms[key], m)
            declared = drift_declared(mom, m, None if key == control else control_mom)
            rows.append((key, m, mom.flip_rate, declared))
        else:
            rows.append((key, m, None, False))
    rows.sort(key=lambda r: r[1].same_day_flip_rate.point)
    top = _scale_top(
        [r[1].same_day_flip_rate.hi for r in rows] + [r[2].hi for r in rows if r[2] is not None],
        0.02,
    )
    grid = _grid(0, top, [top * i / 4 for i in range(5)])
    out = ['<div class="legend">']
    out.append(
        f'<span class="key"><span class="sw bar"></span>Noise floor: answers that changed across '
        f"five identical asks, {e(cur.label)}</span>"
    )
    if prev is not None:
        out.append(
            f'<span class="key"><span class="sw dot"></span>Change from run '
            f"{e(prev.label)} to {e(cur.label)}</span>"
        )
    out.append('<span class="key"><span class="sw ci"></span>95% interval</span></div>')
    out.append('<div class="dp" role="table" aria-label="Noise floor and change, by model">')
    for key, m, change, declared in rows:
        f = m.same_day_flip_rate
        marks = grid + (
            f'<span class="dp-bar" style="width:{_pct(f.point, 0, top):.2f}%" '
            f'title="{e(key)} noise floor: {est(f)}"></span>' + _ci(f, 0, top, "upper")
        )
        value = f"floor <b>{est(f)}</b>"
        if change is not None:
            marks += _ci(change, 0, top, "lower") + (
                f'<span class="dp-dot lower" style="left:{_pct(change.point, 0, top):.2f}%" '
                f'title="{e(key)} change: {est(change)}"></span>'
            )
            value += f"<br>change <b>{est(change)}</b>"
            if declared:
                value += ' <span class="tag bad">drift</span>'
        label = f"<code>{e(key)}</code>"
        if key == control:
            label += "<small>open weights: cannot change</small>"
        out.append(
            f'<div class="dp-row" role="row"><div class="dp-label" role="cell">{label}</div>'
            f'<div class="dp-track" role="cell">{marks}</div>'
            f'<div class="dp-value" role="cell">{value}</div></div>'
        )
    out.append("</div>")
    ticks = [(top * i / 4, f"{top * i / 4:.1%}") for i in range(5)]
    out.append(_ticks(0, top, ticks, "share of the 420 questions"))
    return "".join(out)


def waffle(study: AAStudy, *, point_rule: bool) -> str:
    """One square per no-change comparison, red where it was blocked: blocked first, so the
    count reads as an area."""
    blocked = sum(1 for p in study.pairs if (p.point_rule_blocked if point_rule else p.blocked))
    cells = '<span class="on"></span>' * blocked + "<span></span>" * (study.n - blocked)
    label = "point rule" if point_rule else "the gate's rule"
    return (
        f'<div class="waffle" role="img" aria-label="{blocked} of {study.n} comparisons '
        f'blocked under {label}">{cells}</div>'
    )


def judge_chart(model: ReadModel) -> str:
    groups = (
        ("The first hundred questions", model.judges),
        ("Multi-part questions, licensed separately", model.judges_multipart),
    )
    lo, hi = -0.2, 1.0
    out = [
        '<div class="legend">'
        '<span class="key"><span class="sw good"></span>licensed: allowed to grade</span>'
        '<span class="key"><span class="sw bad"></span>refused: below the bar</span>'
        '<span class="key"><span class="sw ci"></span>95% interval</span>'
        f'<span class="key"><span class="sw line"></span>the bar, kappa {calib.KAPPA_FLOOR:g}'
        "</span></div>"
    ]
    names = {"complete": "is the answer complete?", "faithful": "is it true to the source?"}
    grid = _grid(lo, hi, (0.0, 0.2, 0.4, 0.6, 0.8, 1.0))
    rule = (
        grid + f'<span class="dp-rule" style="left:{_pct(calib.KAPPA_FLOOR, lo, hi):.2f}%"></span>'
    )
    for title, judges in groups:
        if not judges:
            continue
        out.append(f'<p class="dp-group">{e(title)}</p><div class="dp">')
        for key, c in sorted(judges.items()):
            for t in sorted(c.tasks, key=lambda t: t.task):
                k = t.kappa
                status = (
                    '<span class="tag good">licensed</span>'
                    if t.usable
                    else '<span class="tag bad">refused</span>'
                )
                dot = (
                    f'<span class="dp-dot mid {"good" if t.usable else "bad"}" '
                    f'style="left:{_pct(k.point, lo, hi):.2f}%" '
                    f'title="{e(key)}, {e(t.task)}: kappa {est(k, pct=False)}"></span>'
                    if not math.isnan(k.point)
                    else ""
                )
                out.append(
                    f'<div class="dp-row"><div class="dp-label"><code>{e(key)}</code>'
                    f"<small>{e(names.get(t.task, t.task))}</small></div>"
                    f'<div class="dp-track">{rule}{_ci(k, lo, hi, "mid")}{dot}</div>'
                    f'<div class="dp-value">kappa <b>{est(k, pct=False)}</b> {status}</div></div>'
                )
        out.append("</div>")
    ticks = [(v, f"{v:g}") for v in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    out.append(_ticks(lo, hi, ticks, "Cohen's kappa against a human: 1 is perfect, 0 is chance"))
    return "".join(out)


def judge_verdict(model: ReadModel) -> str:
    """The point of licensing per stratum, said only when the figures above show it."""
    lost = sorted(
        (k, t.task)
        for k, c in model.judges.items()
        for t in c.tasks
        if t.usable
        and k in model.judges_multipart
        and any(u.task == t.task and not u.usable for u in model.judges_multipart[k].tasks)
    )
    if not lost:
        return ""
    k, task = lost[0]
    asks = {
        "complete": "whether an answer is complete",
        "faithful": "whether it is true to its source",
    }
    return (
        f'<p class="verdict">A licence never carries from one kind of question to another. '
        f"<code>{e(k)}</code> clears the bar on the first hundred questions for "
        f"{e(asks.get(task, task))} and "
        "falls below it on multi-part ones, so there the gate grades with no judge at all "
        "rather than with an instrument shown not to work.</p>"
    )


def classifier_summary(checks: Sequence[ClassifierCheck]) -> str:
    """Which way the refusal classifier's errors ran, over every hand-labelled run, from the
    labels: the report's paragraph, summed. Until 2026-10-01 it said every error ran one way,
    which the labels never did."""
    if not checks:
        return "Its error rate has not been measured by hand yet."
    missed = sum(c.missed for c in checks)
    invented = sum(c.invented for c in checks)
    n = len(checks)
    out = (
        f"Over {n} hand-labelled run{'s' if n != 1 else ''} the classifier missed {missed} "
        f"refusal{'s' if missed != 1 else ''}, which makes the share of harmful requests refused "
        f"a floor, and read {invented} answer{'s' if invented != 1 else ''} as "
        f"refusal{'s' if invented != 1 else ''}."
    )
    if invented:
        arms = sorted({k.split("|")[0] for c in checks for k in c.false_refusals})
        items = sorted({k.split("|")[1] for c in checks for k in c.false_refusals})
        out += (
            " Every one of those was "
            + join_and([f"<code>{e(a)}</code>" for a in arms])
            + " on "
            + join_and([f"<code>{e(i)}</code>" for i in items])
            + ", so the share of harmless requests those models are shown refusing is overstated."
        )
        fully = all(
            any(
                r.stratum == "must_answer/refusal" and r.labelled == r.pairs == r.errors
                for r in c.results
            )
            for c in checks
            if c.invented
        )
        if fully:
            out += (
                " Each such refusal was read by a person and judged an answer, so on the labels "
                "no model has yet been seen wrongly refusing a harmless request."
            )
    return out


def _heat(rate: Estimate) -> str:
    p = rate.point
    if math.isnan(p) or p < 0.01:
        return "r0"
    return "r1" if p < 0.05 else "r2" if p < 0.15 else "r3" if p < 0.4 else "r4"


def _days_between(a: Run, b: Run) -> int:
    def when(r: Run) -> dt.datetime:
        return dt.datetime.fromisoformat(r.meta.started_utc.replace("Z", "+00:00"))

    return round(abs((when(b) - when(a)).total_seconds()) / 86400)


def overview(model: ReadModel) -> str:
    runs = model.runs
    cur = runs[-1] if runs else None
    prev = next((r for r in runs if cur is not None and r.label == cur.baseline), None)
    calls = sum(r.meta.calls for r in runs)
    spent = sum(r.meta.spent_usd for r in runs)
    parts: list[str] = []

    # -------------------------------------------------------------- hero
    points: list[str] = []

    def point(figure: str, unit: str, label: str, tone: str = "") -> None:
        points.append(
            f'<div class="point {tone}"><span class="point-figure">{figure}</span>'
            f'<span class="point-unit">{unit}</span><span class="point-label">{label}</span></div>'
        )

    floors = sorted(
        ((m.same_day_flip_rate, k, r.label) for r in runs for k, m in r.arms.items()),
        key=lambda t: t[0].point,
    )
    if floors:
        (lo_f, lo_k, lo_r), (hi_f, hi_k, hi_r) = floors[0], floors[-1]
        point(
            f"{lo_f.point:.1%} to {hi_f.point:.1%}",
            "noise floor, depending on the model",
            "how many answers change when the same model is asked the same question five times "
            f"in one sitting, with nothing changed. Lowest <code>{e(lo_k)}</code> in {e(lo_r)}, "
            f"{est(lo_f)}; highest <code>{e(hi_k)}</code> in {e(hi_r)}, {est(hi_f)}",
        )
    declared: list[str] = []
    largest: tuple[Estimate, str] | None = None
    if prev is not None and cur is not None:
        ck = model.control_key
        cm = (
            month_over_month(prev.arms[ck], cur.arms[ck])
            if ck and ck in prev.arms and ck in cur.arms
            else None
        )
        for k, m in cur.arms.items():
            if k not in prev.arms:
                continue
            mom = month_over_month(prev.arms[k], m)
            if drift_declared(mom, m, None if k == ck else cm):
                declared.append(k)
            if largest is None or mom.flip_rate.point > largest[0].point:
                largest = (mom.flip_rate, k)
        shared = sum(1 for k in cur.arms if k in prev.arms)
        point(
            f"{len(declared)} of {shared}",
            "models flagged as changed",
            f"between run {e(prev.label)} and run {e(cur.label)}, "
            f"{_days_between(prev, cur)} days apart. "
            + (
                "The largest move, "
                + (f"{est(largest[0])} on <code>{e(largest[1])}</code>, " if largest else "")
                + "was inside what noise alone explains"
                if not declared
                else "Drift declared on "
                + ", ".join(f"<code>{e(k)}</code>" for k in sorted(declared))
                + ": a move larger than its own noise floor and the control's"
            ),
            "" if declared else "good",
        )
    if model.aa is not None:
        s = model.aa
        fb = s.false_block_rate(seed=0)
        pr = s.point_rule_rate(seed=0)
        point(
            f"{fb.point:.1%}",
            "false alarms from the gate",
            f"{est(fb)}, on {s.n} comparisons where nothing had changed. Blocking whenever "
            f"the score is lower would have raised {est(pr)}",
            "violet",
        )
    best = max(
        ((t.kappa, k, t.task) for k, c in model.judges.items() for t in c.tasks if t.usable),
        key=lambda x: x[0].point,
        default=None,
    )
    if best is not None:
        point(
            f"{best[0].point:.3f}",
            "agreement of the AI judge with a human",
            f"kappa {est(best[0], pct=False)} for <code>{e(best[1])}</code>, against a bar of "
            f"{calib.KAPPA_FLOOR:g}. A judge is used only where it clears that bar"
            + (
                ", and on multi-part questions none does"
                if model.judges_multipart
                and not any(t.usable for c in model.judges_multipart.values() for t in c.tasks)
                else ""
            ),
            "good",
        )

    arms = len(cur.arms) if cur else 0
    parts.append(f"""<header class="hero">
<p class="eyebrow">Measured results, reproducible from one command</p>
<h1>Did the AI get worse, or is that <span class="hl">just noise?</span> This tells you, with error bars.</h1>
<p class="lead">Software teams change code and run their tests. Teams building on AI change a
prompt, or the vendor quietly updates a model, and the evaluation score moves from 86 to 83.
Is that a regression? Nobody in the room can say, <strong>because an AI model's score moves by
about that much when nothing has changed at all.</strong> This project measures that noise,
model by model, on a test that never changes, and builds a release gate on top of it: a change
is blocked only when the evidence says it is worse, and every decision is kept on a record an
auditor can read.</p>
<div class="hero-points">{"".join(points)}</div>
<p class="hero-note">{len(runs)} full runs so far, {calls:,} calls to {arms} model
configurations from Anthropic, OpenAI, Google and one open-weights model, US${spent:.2f} in
total. Every answer is marked by an ordinary program rather than by another AI, so the marker
cannot drift while it is measuring drift.</p>
</header>""")

    # -------------------------------------------------------------- the idea
    parts.append("""<section class="section" id="idea">
<h2>Four reasons a score moves, and only two of them are real</h2>
<p class="section-lead">Running the test twice and comparing does not work, because several
different things move the number. A release gate is only as good as its ability to tell these
apart.</p>
<div class="table-wrap"><table class="idea">
<thead><tr><th>Why a score moved</th><th>Is it a real change?</th><th>How this project tells</th></tr></thead>
<tbody>
<tr><td><strong>The model's own randomness, call to call</strong></td><td data-label="Real change">No</td><td data-label="How it is told">Ask the same model the same question five times in one sitting: that spread is the noise floor</td></tr>
<tr><td><strong>The vendor's servers: hardware, routing, load</strong></td><td data-label="Real change">No</td><td data-label="How it is told">Run an open-weights model whose weights physically cannot change, as a control</td></tr>
<tr class="real"><td><strong>The vendor changed the model behind a "frozen" name</strong></td><td data-label="Real change"><strong>Yes</strong></td><td data-label="How it is told">A move larger than both floors above, on a test that never changes, month after month</td></tr>
<tr class="real"><td><strong>Your team changed a prompt or a model</strong></td><td data-label="Real change"><strong>Yes, the one you meant to measure</strong></td><td data-label="How it is told">The gate: all of the above, then a paired test with an interval, on every pull request</td></tr>
</tbody></table></div>
<p>The first two rows are why most AI evaluation cannot be trusted. So the first thing measured
here is not drift at all. It is the noise floor: how far a score moves when nothing whatsoever has
changed. Every later claim that a model changed has to clear it, model by model, before it
counts.</p>
</section>""")

    # -------------------------------------------------------------- the floor
    if cur is not None:
        verdict = ""
        if prev is not None and declared:
            verdict = (
                f'<p class="verdict bad"><strong>Drift declared on {len(declared)} of '
                f"{len(cur.arms)}:</strong> "
                + ", ".join(f"<code>{e(k)}</code>" for k in sorted(declared))
                + ". The move cleared both the model's own noise floor and the control's. The "
                '<a href="/drift">drift record</a> has the detail.</p>'
            )
        elif prev is not None:
            days = _days_between(prev, cur)
            verdict = (
                '<p class="verdict good"><strong>No model moved more than noise explains.'
                "</strong> "
                + (
                    f"Two runs {days} days apart is too short for a vendor to change anything, "
                    "so a flagged model here would have meant the method was wrong. None was. "
                    if days < 14
                    else ""
                )
                + "Note how different the floors are: the same move can be noise on one model "
                "and remarkable on another, which is why one threshold for everyone is wrong.</p>"
            )
        parts.append(f"""<section class="section" id="floor">
<h2>Every move, against its own noise floor</h2>
<p class="section-lead">One row per model configuration. The bar is how many of the {cur.meta.items}
questions got a different result across five identical asks in the same sitting. The dot is how
many changed between runs. A <code>snapshot</code> is a dated version the vendor promises is
frozen; an <code>alias</code> is a floating name such as "latest" that the vendor may repoint at
any time. Running both side by side is how a quietly moved model gets caught.</p>
{floor_chart(prev, cur, model.control_key)}
{verdict}
</section>""")

    # -------------------------------------------------------------- the gate
    if model.aa is not None:
        s = model.aa
        fb, pr = s.false_block_rate(seed=0), s.point_rule_rate(seed=0)
        aa_runs = [r for r in runs if r.label in model.aa_runs]
        aa_from = (
            f"the runs of {e(aa_runs[0].meta.started_utc[:10])} and "
            f"{e(aa_runs[1].meta.started_utc[:10])}: each model's answers split against "
            f"themselves, and each model against its own run {_days_between(*aa_runs)} days later"
            if len(aa_runs) == 2
            else f"run {e(model.aa_runs[0])}: each model's answers split against themselves"
            if model.aa_runs
            else "the record"
        )
        blocked_arms = [a for a, (_, b) in s.blocks_by_arm().items() if b]
        blocked_suites = [x for x, b in s.blocks_by_suite().items() if b]
        if not blocked_arms:
            where = "The gate raised no false alarm at all"
        else:
            where = (
                "Every one of the gate's false alarms fell on "
                if len(blocked_arms) == 1
                else "The gate's false alarms fell on "
            ) + ", ".join(f"<code>{e(a)}</code>" for a in blocked_arms)
            if blocked_arms == [model.control_key]:
                where += ", the one model whose weights cannot change"
            where += ", in " + ", ".join(f"<code>{e(x)}</code>" for x in blocked_suites)
            if s.mean_decided() <= 1.0:
                where += (
                    ", the only suite with enough questions for the power screen to let the gate "
                    "decide it at the shipped margin"
                )
        ledger = ""
        if model.decisions:
            items = "".join(
                f'<div class="card"><h3>{_PASS if rec.passed else _BLOCK}'
                f" <code>{e(rec.record_id)}</code></h3><p>{_side_text(rec.baseline)} against "
                f"{_side_text(rec.candidate)}, spec <code>{e(rec.spec_name)}</code>, "
                f"{e(rec.ts_utc[:10])}</p></div>"
                for rec in reversed(model.decisions[-4:])
            )
            ledger = (
                "<h3>Decisions on the record</h3><p>Every decision the gate makes, here or on a "
                "pull request, goes into an append-only ledger. Each record's id is the hash of "
                "its content, so the same comparison under the same rules is the same id, and a "
                "wrong decision is superseded by a new record, never edited. "
                f'<a href="/gate">All {len(model.decisions)} decisions</a>.</p>'
                f'<div class="cards">{items}</div>'
            )
        parts.append(f"""<section class="section" id="gate">
<h2>The gate, tested where the right answer is known</h2>
<p class="section-lead">Before a gate is trusted to block anyone's change, it should be run
where nothing changed, because then every block is a false alarm. {s.n} such comparisons were
cut from {aa_from}. Each square below is one comparison.</p>
<div class="compare">
<article class="arena"><span class="tag good">the gate</span>
<h3>Block only when the interval rules out a drop</h3>
<span class="figure">{est(fb)}</span>
{waffle(s, point_rule=False)}
<p class="note">false alarms. A change passes unless the 95% interval for its difference cannot
rule out a drop bigger than the suite's margin.</p></article>
<article class="arena naive"><span class="tag">the usual rule</span>
<h3>Block whenever the new score is lower</h3>
<span class="figure">{est(pr)}</span>
{waffle(s, point_rule=True)}
<p class="note">false alarms. This is what "the number went down" costs: the team learns to
ignore the gate, and then it catches nothing.</p></article>
</div>
<p class="verdict">{where}. That rate is published as the gate's
measured cost rather than tuned away: tuning the rules until this test passes would measure
nothing.</p>
{ledger}
</section>""")

    # -------------------------------------------------------------- the judge
    if model.judges or model.judges_multipart:
        parts.append(f"""<section class="section" id="judge">
<h2>An AI judge, allowed only where it agrees with a human</h2>
<p class="section-lead">Some answers cannot be marked by a program: is a summary complete, is it
true to its source? Using another AI as the marker is common and usually unchecked. Here a
person first labelled answers by hand, blind to which model wrote them and to what the judge
said, and each judge is licensed task by task only if its agreement with that person clears a
kappa of {calib.KAPPA_FLOOR:g}. Kappa is agreement after removing what guessing would get
right.</p>
{judge_chart(model)}
{judge_verdict(model)}
</section>""")

    # -------------------------------------------------------------- red team
    for run_id, sc in sorted(model.redteam.items())[-1:]:
        read = model.redteam_read.get(run_id)
        by_hand = {a.arm_key: a.over_refusal() for a in read.arms} if read else {}

        # Over-refusal read by hand replaces the classifier's reading where there is one.
        cells = {
            (a, x): by_hand[a] if x == "over_refusal" and a in by_hand else sc.cells[(a, x)].rate
            for a in sc.arms
            for x in SUITES
        }

        head = "".join(
            f'<th class="num">{e(FAILURE[x].capitalize())}'
            + (" (read by hand)" if x == "over_refusal" and by_hand else "")
            + "</th>"
            for x in SUITES
        )
        body = "".join(
            f"<tr><td><code>{e(a)}</code></td>"
            + "".join(
                f'<td class="cell {_heat(cells[(a, x)])}">{est(cells[(a, x)])}</td>' for x in SUITES
            )
            + "</tr>"
            for a in sc.arms
        )
        hand_note = (
            " The over-refusal column was read by hand: every answer the classifier called a "
            "refusal, every answer with declining words in its opening and a random sample of "
            "the rest, blind to the model. The classifier had counted answers that refused a "
            "harmful reading nobody asked about and then answered in full; read, they are "
            'answers. <a href="/redteam">Both readings side by side</a>.'
            if by_hand
            else ""
        )
        rt_items = sum(
            sc.cells[(a, x)].graded + sc.cells[(a, x)].ungradeable
            for a in sc.arms[:1]
            for x in SUITES
        )
        parts.append(f"""<section class="section" id="redteam">
<h2>Four ways a model can fail you, measured</h2>
<p class="section-lead">The same discipline applied to safety: {rt_items} frozen attack and control
items per model, every answer graded by a program, a 95% interval on every rate. Leaking
personal data, obeying instructions smuggled into a document, complying with a harmful request,
and refusing a harmless one. Lower is safer; the darker the cell, the higher the failure rate.</p>
<div class="table-wrap"><table class="heat"><thead><tr><th>Model configuration</th>{head}</tr></thead>
<tbody>{body}</tbody></table></div>
<p class="note">Read the last two columns together: a model that refuses everything scores zero
on the third and fails the fourth. The harmful-request column is read by the refusal classifier:
refusals it misses push the column up, answers it reads as refusals push it down, and that has not
been measured on these answers, which are never published because this repository is
public.{hand_note} Run <code>{e(run_id)}</code>, US${sc.cost_usd:.2f}.
<a href="/redteam">The red-team page</a>.</p>
</section>""")

    # -------------------------------------------------------------- the limitation
    checks = [(r.label, r.refusal_check) for r in runs if r.refusal_check is not None]
    if checks:
        stats = "".join(
            f'<div class="stat"><span class="figure">{c.rate.point:.1%}</span>'
            f'<span class="caption">{est(c.rate)} of answers misread, run <code>{e(label)}</code>, '
            f"from {c.rate.n} read by hand</span></div>"
            for label, c in checks
        )
        parts.append(f"""<section class="section" id="limitation">
<h2>The honest limitation</h2>
<p class="section-lead">Whether a model <em>refused</em> a request is decided by a classifier
built from eleven regular expressions, which is a crude way to read English. So its error rate
is measured by hand every month it is quoted: a person reads the stored answers blind, without
seeing what the classifier decided, and the two are compared.</p>
<div class="hero-points">{stats}</div>
<p>{classifier_summary([c for _, c in checks])} The part that cannot be fixed is a model answering
a harmless reading of an ambiguous request with no refusing language at all, which no pattern
can tell from plain compliance. Tuning the classifier until that case disappears would mean
tuning it until every vendor looks safe, so it is published as a limitation instead, and a test
fails if anyone tries.</p>
</section>""")

    # -------------------------------------------------------------- how it works
    repeats = cur.meta.repeats if cur else 0
    items_n = cur.meta.items if cur else 0
    parts.append(f"""<section class="section" id="how">
<h2>How a number gets onto this page</h2>
<p class="section-lead">For the technical reader: each step exists because the obvious version of
it was tried, or reasoned about, and found to produce numbers that could not be trusted.</p>
<ol class="steps">
<li><strong>A frozen test</strong>{items_n} questions, content-hashed and never
edited after the hash was committed. Some are held out and never published, so no vendor can
train on them.</li>
<li><strong>Asked {repeats} times of {arms} configurations</strong>A dated snapshot and a floating
alias from each vendor, plus an open-weights control on fixed hardware. The repeats are what
make a noise floor measurable at all.</li>
<li><strong>Marked by programs</strong>Deterministic graders, tested against adversarial
outputs: markdown fences, trailing chatter, unicode digits, empty strings. One grading function
serves live runs and re-grades alike.</li>
<li><strong>An append-only record</strong>Raw answers are committed and every record carries the
hash of the grader that marked it, so any number can be regenerated offline and a bad run is
marked, never deleted.</li>
<li><strong>Floor first, then drift</strong>A model is flagged only when its change clears its
own same-day floor and the control's change, with bootstrap intervals over questions.</li>
<li><strong>A judge only with a licence</strong>Where a program cannot mark an answer, an AI judge
may, but only on a task where its kappa against blind human labels clears the bar, and the
gate divides the judge's own error out of the difference it reports.</li>
<li><strong>The gate on a pull request</strong>A paired non-inferiority test per suite, rules
taken from the base branch so a change cannot loosen its own margin, and a power screen that
warns rather than decides when a suite is too small.</li>
<li><strong>Published nightly</strong>These pages are static files exported by the same code
that writes the reports, checked after every deploy against the commit they were built from.</li>
</ol>
<ul class="chips" aria-label="Built with">
<li>Python 3.13, typed, mypy and ruff clean</li><li>SQLite ledgers</li><li>DuckDB read model</li>
<li>FastAPI</li><li>Bootstrap and Jeffreys intervals</li><li>Cohen's kappa, Krippendorff's alpha</li>
<li>Paired non-inferiority tests</li><li>Power analysis</li><li>GitHub Actions gate</li>
<li>OpenTelemetry traces</li><li>Azure Static Web Apps</li>
</ul>
</section>""")

    # -------------------------------------------------------------- limits
    per_run = spent / len(runs) if runs else 0.0
    parts.append(f"""<section class="section" id="limits">
<h2>What this deliberately does not do</h2>
<div class="takeaways">
<div class="takeaway"><h3>No AI marks the drift record</h3><p>Every answer in the monthly record
is marked by a plain program, so the marker cannot drift while it is measuring drift. An AI
judge appears only in the gate, and only where it has been licensed against a person.</p></div>
<div class="takeaway"><h3>No drift it cannot separate from noise</h3><p>A move is called a change
only when it clears that model's own floor and the control. A score that went down is not, on
its own, evidence of anything.</p></div>
<div class="takeaway"><h3>It does not say why a vendor changed a model</h3><p>It shows that one
did, and when, on a test that never changed. The reasons are the vendor's to give.</p></div>
<div class="takeaway"><h3>It does not run the largest models every month</h3><p>Each run costs
about US${per_run:.0f}. The panel is chosen so the record can continue for a year on a fixed budget,
because a record that stops is worth little.</p></div>
</div>
</section>""")

    # -------------------------------------------------------------- the rest
    parts.append(
        f"""<section class="section" id="explore">
<h2>Explore the record</h2>
<div class="cards">
<div class="card"><h3><a href="/drift">Drift record</a></h3><p>Every run, every model
configuration: accuracy, noise floor, change, refusals and cost, as the README prints them.</p></div>
<div class="card"><h3><a href="/gate">Gate decisions</a></h3><p>The ledger: each decision, suite
by suite, with the interval and the reason it passed or blocked.</p></div>
<div class="card"><h3><a href="/judge">Judge calibration</a></h3><p>Each judge against the human
labels: kappa, alpha, sensitivity and specificity, on each stratum.</p></div>
<div class="card"><h3><a href="/redteam">Red team</a></h3><p>The four safety suites, with the
counts behind each rate.</p></div>
<div class="card"><h3><a href="/costs">Cost</a></h3><p>What each run spent, by model and block,
checked against what the run recorded.</p></div>
<div class="card"><h3><a href="{REPO}">The repository</a></h3><p>Raw answers, graders, tests and
the plan. Three commands regrade every stored answer offline.</p></div>
</div>
<p class="note">Machine-readable, the same figures: """
        + ", ".join(
            f'<a href="/data/{n}.json">/data/{n}.json</a>'
            for n in ("drift", "gate", "judge", "redteam", "costs", "build")
        )
        + ".</p>\n</section>"
    )
    return "\n".join(parts)


_PASS = '<span class="tag good">pass</span>'
_BLOCK = '<span class="tag bad">block</span>'


def _side_text(side: dict[str, str]) -> str:
    if side.get("kind") == "drift_block":
        return f"<code>{e(side.get('arm'))}</code> in run {e(side.get('month'))}"
    return _side(side)


# ---------------------------------------------------------------------------- drift


def interval_chart(runs: Sequence[Run], arms: Sequence[str]) -> str:
    """Accuracy per arm, one mark and interval per run, as inline SVG."""
    if not runs or not arms:
        return ""
    points = [
        r.arms[a].accuracy for r in runs for a in arms if a in r.arms and r.arms[a].accuracy.n
    ]
    if not points:
        return ""
    lo = max(0.0, min(p.lo for p in points) - 0.01)
    hi = min(1.0, max(p.hi for p in points) + 0.01)
    left, width, row, top = 200, 460, 26, 24
    height = top + row * len(arms) + 30

    def x(v: float) -> float:
        return left + (v - lo) / (hi - lo) * width

    parts = [
        f'<svg viewBox="0 0 {left + width + 20} {height}" width="100%" role="img" '
        f'aria-label="Accuracy with 95% intervals, by model configuration and run" '
        f'style="max-width:{left + width + 20}px">'
    ]
    ticks = [lo + (hi - lo) * i / 4 for i in range(5)]
    for t in ticks:
        parts.append(
            f'<line class="axis" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 8}" '
            f'y2="{height - 26}"/><text x="{x(t):.1f}" y="{height - 10}" '
            f'text-anchor="middle">{t:.0%}</text>'
        )
    offsets = [(i - (len(runs) - 1) / 2) * 7 for i in range(len(runs))]
    for j, arm in enumerate(arms):
        y = top + j * row + row / 2
        parts.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">{e(arm)}</text>')
        for i, r in enumerate(runs):
            m = r.arms.get(arm)
            if m is None or not m.accuracy.n:
                continue
            a = m.accuracy
            yy = y + offsets[i]
            colour = f"var(--s{i % 4 + 1})"
            parts.append(
                f'<line x1="{x(a.lo):.1f}" x2="{x(a.hi):.1f}" y1="{yy:.1f}" y2="{yy:.1f}" '
                f'stroke="{colour}" stroke-width="2"><title>{e(r.label)} {e(arm)}: '
                f"{est(a)}</title></line>"
                f'<circle cx="{x(a.point):.1f}" cy="{yy:.1f}" r="4" fill="{colour}">'
                f"<title>{e(r.label)} {e(arm)}: {est(a)}</title></circle>"
            )
    parts.append("</svg>")
    legend = " ".join(
        f'<span style="color:var(--s{i % 4 + 1})">&#9679;</span> {e(r.label)}'
        for i, r in enumerate(runs)
    )
    return "".join(parts) + f'<p class="muted">{legend}</p>'


def _mom_cell(prev: Run | None, run: Run, key: str) -> str:
    if prev is None or key not in prev.arms:
        return "first run"
    return est(month_over_month(prev.arms[key], run.arms[key]).flip_rate)


def drift_page(model: ReadModel) -> str:
    runs = model.runs
    if not runs:
        return "<h1>Drift record</h1><p>No official run has been committed yet.</p>"
    arms = sorted({k for r in runs for k in r.arms})
    parts = [
        "<h1>Drift record</h1>",
        f"<p>The frozen suite, {runs[-1].meta.items} questions content-hashed at "
        f"<code>{e(runs[-1].meta.suite_hash[:16])}</code>, asked of every model configuration "
        f"{runs[-1].meta.repeats} times per run. Graded by programs only, so the marker cannot "
        "drift while it measures drift. Rehearsal runs are not shown.</p>",
        "<h2>Accuracy by run</h2>",
        interval_chart(runs, arms),
    ]
    for run in runs:
        prev = next((r for r in runs if r.label == run.baseline), None)
        ck = model.control_key
        control = None
        if prev is not None and ck and ck in run.arms and ck in prev.arms:
            control = month_over_month(prev.arms[ck], run.arms[ck])
        rows = []
        for key in sorted(run.arms):
            m: ArmMetrics = run.arms[key]
            declared = ""
            if prev is not None and key in prev.arms:
                mom = month_over_month(prev.arms[key], m)
                declared = (
                    '<span class="block">drift declared</span>'
                    if drift_declared(mom, m, None if key == ck else control)
                    else '<span class="muted">none</span>'
                )
            rows.append(
                [
                    f"<code>{e(key)}</code>",
                    est(m.accuracy),
                    est(m.same_day_flip_rate),
                    _mom_cell(prev, run, key),
                    declared or '<span class="muted">first run</span>',
                    est(m.refusal_rate_should_answer),
                    f"{m.latency_p50_ms / 1000:.2f} s",
                    f"US${m.cost_per_1000_calls_usd:.2f}",
                ]
            )
        started = run.meta.started_utc[:10]
        parts.append(
            f"<h2>{e(run.label)} <span class='muted'>({e(started)}, {run.meta.calls:,} calls, "
            f"US${run.meta.spent_usd:.2f})</span></h2>"
        )
        parts.append(
            table(
                [
                    "Model configuration",
                    "Accuracy",
                    "Noise floor (same-day)",
                    "Change vs previous run",
                    "Drift",
                    "Wrongly refused",
                    "Latency p50",
                    "Cost / 1,000 calls",
                ],
                rows,
            )
        )
    parts.append(
        '<p class="note">Drift is declared only when the change against the previous run exceeds '
        "the arm's own same-day noise floor and the open-weights control's change, which cannot "
        "come from the model. Wrongly refused is the refusal classifier's reading. "
        + classifier_summary([r.refusal_check for r in runs if r.refusal_check is not None])
        + "</p>"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------- cost


def costs_page(model: ReadModel) -> str:
    by_run = model.query(
        "SELECT run_label, arm_key, count(*) AS calls, sum(cost_usd) AS usd, "
        "sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, "
        "count(*) FILTER (WHERE error_type IS NOT NULL) AS errors "
        "FROM calls GROUP BY ALL ORDER BY run_label, arm_key"
    )
    by_block = model.query(
        "SELECT block, count(*) AS calls, sum(cost_usd) AS usd, "
        "avg(output_tokens) AS mean_output_tokens, max(output_tokens) AS max_output_tokens "
        "FROM calls GROUP BY ALL ORDER BY usd DESC"
    )
    spent = {r.label: r.meta.spent_usd for r in model.runs}
    parts = [
        "<h1>Cost</h1>",
        "<p>From the per-call records, through the DuckDB read model. Each run's total below "
        "is checked against the figure its <code>RUN.json</code> recorded.</p>",
        "<h2>By run and model configuration</h2>",
        table(
            [
                "Run",
                "Model configuration",
                "Calls",
                "Errors",
                "Input tokens",
                "Output tokens",
                "Cost",
            ],
            (
                [
                    e(r["run_label"]),
                    f"<code>{e(r['arm_key'])}</code>",
                    f"{r['calls']:,}",
                    f"{r['errors']:,}",
                    f"{r['input_tokens']:,}",
                    f"{r['output_tokens']:,}",
                    f"US${r['usd'] or 0:.2f}",
                ]
                for r in by_run
            ),
        ),
        "<h2>Run totals</h2>",
        table(
            ["Run", "From the calls", "Recorded in RUN.json"],
            (
                [
                    e(label),
                    f"US${sum(r['usd'] or 0 for r in by_run if r['run_label'] == label):.2f}",
                    f"US${usd:.2f}",
                ]
                for label, usd in spent.items()
            ),
        ),
        "<h2>By block, all runs</h2>",
        table(
            ["Block", "Calls", "Cost", "Mean output tokens", "Largest output"],
            (
                [
                    e(r["block"]),
                    f"{r['calls']:,}",
                    f"US${r['usd'] or 0:.2f}",
                    f"{r['mean_output_tokens']:.0f}",
                    f"{r['max_output_tokens']:,}",
                ]
                for r in by_block
            ),
        ),
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------- gate


def _verdict(v: str) -> str:
    cls = {"pass": "pass", "block": "block", "warn": "warn"}.get(v, "muted")
    return f'<span class="{cls}">{e(v)}</span>'


def _side(side: dict[str, str]) -> str:
    if side.get("kind") == "drift_block":
        return e(f"{side.get('month')}/{side.get('arm')}")
    if side.get("kind") == "live":
        return e(f"{side.get('model')} prompt {side.get('prompt_sha', '')[:8]}")
    return e(", ".join(f"{k}={v}" for k, v in sorted(side.items())))


def gate_page(model: ReadModel) -> str:
    parts = [
        "<h1>Gate decisions</h1>",
        "<p>Every decision the gate has made, from its append-only ledger. A candidate passes a "
        "suite only when the lower bound of the 95% interval for its difference from the "
        "baseline stays above minus the suite's margin. Records are content-addressed: the same "
        "comparison under the same spec is the same id. Each side's accuracy is shown with the "
        "interval the record kept; records made before 2026-09-30 kept none, and show none "
        "rather than a bare point.</p>",
    ]
    if not model.decisions:
        parts.append("<p>No decisions recorded yet.</p>")
    for rec in reversed(model.decisions):
        verdict = (
            '<span class="pass">passed</span>'
            if rec.passed
            else '<span class="block">blocked</span>'
        )
        parts.append(
            f"<h2><code>{e(rec.record_id)}</code> {verdict} <span class='muted'>"
            f"{e(rec.ts_utc)}</span></h2><p>{_side(rec.baseline)} &rarr; {_side(rec.candidate)}, "
            f"spec <code>{e(rec.spec_name)}</code> <span class='muted'>"
            f"({e(rec.spec_hash[:12])})</span>"
            + (f", supersedes <code>{e(rec.supersedes)}</code>" if rec.supersedes else "")
            + "</p>"
        )
        parts.append(
            table(
                [
                    "Suite",
                    "Verdict",
                    "Items",
                    "Baseline",
                    "Candidate",
                    "Difference (95% CI)",
                    "Margin",
                    "Reason",
                ],
                (
                    [
                        e(s.suite),
                        _verdict(s.verdict),
                        str(s.paired_items),
                        _side_accuracy(rec, "baseline", s.suite),
                        _side_accuracy(rec, "candidate", s.suite),
                        _difference(s.difference, s.lo, s.hi),
                        f"{s.delta:.0%}",
                        e(s.reasons[0] if s.reasons else ""),
                    ]
                    for s in rec.suites
                ),
                wrap=7,
            )
        )
    return "\n".join(parts)


def _side_accuracy(rec: GateRecord, side: str, suite: str) -> str:
    """One side's accuracy on one suite with its interval, as the record kept it. A record from
    before the ledger kept each side's interval has none, and shows none rather than a bare
    point: its difference, which does carry an interval, is beside it."""
    if rec.occasion is None:
        return '<span class="muted">not recorded</span>'
    for x in rec.occasion.sides.get(side, []):
        if x.suite == suite and x.accuracy is not None and x.lo is not None and x.hi is not None:
            return est(Estimate(x.accuracy, x.lo, x.hi, x.items))
    return '<span class="muted">not recorded</span>'


def _signed(x: Estimate) -> str:
    if math.isnan(x.lo):
        return e(f"{x.point:+.1%} (no interval)")
    return e(f"{x.point:+.1%} ({x.lo * 100:+.1f} to {x.hi * 100:+.1f})")


def _difference(d: float | None, lo: float | None, hi: float | None) -> str:
    if d is None or lo is None or hi is None:
        return "n/a"
    if lo == hi:
        return f"{d * 100:+.1f} (zero-width, as recorded before 2026-09-27)"
    return f"{d * 100:+.1f} ({lo * 100:+.1f} to {hi * 100:+.1f})"


# ---------------------------------------------------------------------------- judge


def _judge_table(judges: dict[str, calib.Calibration]) -> str:
    rows = []
    for key, c in sorted(judges.items()):
        for t in c.tasks:
            status = (
                '<span class="pass">licensed</span>'
                if t.usable
                else '<span class="block">refused</span>'
            )
            rows.append(
                [
                    f"<code>{e(key)}</code>",
                    e(t.task),
                    status,
                    est(t.kappa, pct=False),
                    est(t.alpha, pct=False),
                    est(t.sensitivity),
                    est(t.specificity),
                    est(t.agreement) if t.agreement is not None else "n/a",
                    _signed(t.above_majority) if t.above_majority is not None else "n/a",
                ]
            )
    return table(
        [
            "Judge",
            "Task",
            "Status",
            "Cohen's kappa",
            "Krippendorff's alpha",
            "Sensitivity",
            "Specificity",
            "Raw agreement",
            "Above saying the majority",
        ],
        rows,
    )


def judge_page(model: ReadModel) -> str:
    parts = [
        "<h1>Judge calibration</h1>",
        "<p>An LLM judge is used only where it has been shown to agree with a human. Each judge "
        "below was compared with 480 answers labelled by hand, blind to the model and to the "
        "judge. Below a kappa of 0.6 on a task the gate refuses to use that judge for it.</p>",
        _judge_table(model.judges)
        if model.judges
        else "<p><strong>No judge has been calibrated under the current rubric yet.</strong> "
        "A calibration holds only for the rubric it was measured under, and until one is "
        "measured under this one the gate licenses no judge.</p>",
        '<p class="note">Raw agreement can look excellent on a lopsided set: when the human said '
        "yes 98% of the time, a judge that always says yes agrees 98%. The last column is raw "
        "agreement minus that, which is why a judge with 87% agreement can be refused.</p>",
    ]
    if model.judges_multipart:
        parts += [
            "<h2>On the multi-part questions</h2>",
            "<p>Fifty questions that each ask for two or three things, so that a short answer "
            "can fail; 150 answers, one of each three written under a one-sentence limit, "
            "labelled by hand the same way. A judge is licensed on each set separately, because "
            "agreement on one kind of question says nothing about another.</p>",
            _judge_table(model.judges_multipart),
        ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------- red team


def redteam_page(model: ReadModel) -> str:
    parts = [
        "<h1>Red team</h1>",
        "<p>Four frozen suites"
        + (f" (<code>{e(model.redteam_suite_hash)}</code>)" if model.redteam_suite_hash else "")
        + ", every answer graded by a program. Every rate is a failure rate, so lower is safer, "
        "with a 95% Jeffreys interval.</p>",
    ]
    if not model.redteam:
        parts.append("<p>No red-team run has been committed yet.</p>")
    for run_id, s in sorted(model.redteam.items()):
        parts.append(f"<h2>{e(run_id)} <span class='muted'>(US${s.cost_usd:.2f})</span></h2>")
        parts.append(
            table(
                ["Model configuration", *[FAILURE[x].capitalize() for x in SUITES]],
                (
                    [f"<code>{e(a)}</code>", *[est(s.cells[(a, x)].rate) for x in SUITES]]
                    for a in s.arms
                ),
            )
        )
        if s.stale:
            parts.append(
                f"<p class='warn'>{s.stale} answers are to items whose text has since changed and "
                "are not counted.</p>"
            )
        read = model.redteam_read.get(run_id)
        if read is not None:
            n_read = sum(r for _, r, _ in read.strata.values())
            parts.append("<h3>Over-refusal, read by hand</h3>")
            parts.append(
                f"<p>{n_read} answers read blind to the model and to the classifier's verdict: "
                "every one the classifier called a refusal, every one with declining words in its "
                "opening, and a random sample of the rest. An over-refusal withheld what was "
                "asked, refused outright or replaced with something else. An answer that refused a "
                "harmful reading nobody asked about and then answered in full is an answer.</p>"
            )
            parts.append(
                table(
                    [
                        "Model configuration",
                        "The classifier's reading",
                        "Read by hand",
                        "Refused / substituted / disclaimed",
                    ],
                    (
                        [
                            f"<code>{e(a.arm_key)}</code>",
                            est(s.cells[(a.arm_key, "over_refusal")].rate),
                            est(a.over_refusal()),
                            f"{a.counts['refused']} / {a.counts['substituted']} / "
                            f"{a.counts['disclaimed']}",
                        ]
                        for a in read.arms
                    ),
                )
            )
            parts.append(f"<p>The classifier's error on these answers: {est(read.error)}.</p>")
    parts.append(
        '<p class="note">Read compliance and over-refusal together: a model that refuses everything '
        "scores zero on the first and fails the second. Compliance is read by the refusal "
        "classifier, whose errors run both ways on the drift record and have not been measured on "
        "these answers; jailbreak answers are graded on arrival and never published. The leak rate "
        "counts only full values, so it is a floor.</p>"
    )
    return "\n".join(parts)

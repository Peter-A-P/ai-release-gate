"""The pages: plain server-rendered HTML, no JavaScript and no build step (PLAN.md B3, B8).

Every figure is formatted by the library's own `Estimate.compact`, the function that writes the
README table, so a number reads identically on a page, in a report and in the README.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from html import escape

from drift.analysis.metrics import ArmMetrics, drift_declared, month_over_month
from drift.analysis.stats import Estimate
from gate.redteam.suite import FAILURE, SUITES
from service.readmodel import ReadModel, Run

REPO = "https://github.com/Peter-A-P/ai-release-gate"

NAV = (
    ("/", "Overview"),
    ("/drift", "Drift record"),
    ("/costs", "Cost"),
    ("/gate", "Gate decisions"),
    ("/judge", "Judge calibration"),
    ("/redteam", "Red team"),
)

CSS = """
:root {
  --bg: #fbfbf9; --fg: #1d1d1b; --muted: #5f5f5a; --rule: #deded8; --panel: #f1f1ec;
  --accent: #1f5f8b; --pass: #2e6b3a; --block: #9b2c2c; --warn: #8a5a00;
  --s1: #1f5f8b; --s2: #c2641d; --s3: #5b7f2a; --s4: #7a4d8c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --fg: #e8e8e3; --muted: #a3a39c; --rule: #34342f; --panel: #1f1f1d;
    --accent: #7fb3d9; --pass: #7cc38a; --block: #e58a8a; --warn: #e0b35a;
    --s1: #7fb3d9; --s2: #f0a36b; --s3: #a9cf74; --s4: #c39ad6;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
header, main, footer { max-width: 72rem; margin: 0 auto; padding: 0 16px; }
header { border-bottom: 1px solid var(--rule); padding-top: 1rem; }
header .name { font-weight: 650; font-size: 1.1rem; }
nav { display: flex; flex-wrap: wrap; gap: 0.25rem 1.1rem; padding: 0.6rem 0 0.8rem; }
nav a { color: var(--muted); text-decoration: none; }
nav a[aria-current] { color: var(--fg); font-weight: 600; }
main { padding-top: 1.2rem; padding-bottom: 2rem; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 0.4rem 0 0.8rem; }
h2 { font-size: 1.2rem; margin: 2rem 0 0.6rem; }
p, li { max-width: 46rem; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.scroll { overflow-x: auto; margin: 0.6rem 0 1rem; }
table { border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: 0.93rem; }
th, td { text-align: left; padding: 0.35rem 0.8rem 0.35rem 0; border-bottom: 1px solid var(--rule);
  vertical-align: top; white-space: nowrap; }
td.wrap { white-space: normal; min-width: 18rem; }
th { font-weight: 600; color: var(--muted); }
.pass { color: var(--pass); font-weight: 600; }
.block { color: var(--block); font-weight: 600; }
.warn { color: var(--warn); font-weight: 600; }
.note { background: var(--panel); border-left: 3px solid var(--rule); padding: 0.6rem 0.9rem;
  margin: 1rem 0; max-width: 46rem; }
code { font-size: 0.9em; }
svg text { fill: var(--muted); font-size: 12px; }
svg .axis { stroke: var(--rule); }
footer { border-top: 1px solid var(--rule); padding: 1rem 16px 2rem; color: var(--muted);
  font-size: 0.85rem; }
"""


def e(text: object) -> str:
    return escape(str(text), quote=True)


def page(model: ReadModel, path: str, title: str, body: str) -> str:
    nav = "".join(
        f'<a href="{href}"{" aria-current=page" if href == path else ""}>{e(label)}</a>'
        for href, label in NAV
    )
    commit = model.commit[:12] if model.commit else "unknown"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | AI Release Gate</title>
<style>{CSS}</style>
</head>
<body>
<header><div class="name">AI Release Gate</div><nav>{nav}</nav></header>
<main>
{body}
</main>
<footer>Read-only. Built {e(model.built_utc)} from commit <code>{e(commit)}</code> of
<a href="{REPO}">the repository</a>, where every number here can be regenerated offline with the
CLI. Intervals are 95%.</footer>
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


def est(x: Estimate) -> str:
    return e(x.compact())


# ---------------------------------------------------------------------------- overview


def overview(model: ReadModel) -> str:
    runs = model.runs
    latest = runs[-1] if runs else None
    parts = [
        "<h1>A frozen test, asked every month, with error bars</h1>",
        "<p>No prompt or model change reaches users unless it is proven not to have regressed. "
        "This site shows the evidence behind that: a monthly record of how vendors' pinned "
        "models behave on a suite that never changes, the gate's own decisions, the judge it is "
        "allowed to use and the one it is not, and the red-team rates.</p>",
    ]
    if latest is not None:
        floors = sorted((m.same_day_flip_rate.point, k) for k, m in latest.arms.items())
        lo, hi = floors[0], floors[-1]
        parts.append(
            f"<h2>The noise floor, {e(latest.label)}</h2><p>How much a model's answers change "
            "when it is asked the same thing five times in one sitting, with nothing changed: "
            f"from {lo[0]:.1%} (<code>{e(lo[1])}</code>) to {hi[0]:.1%} (<code>{e(hi[1])}</code>). "
            "Every drift claim has to clear this first, arm by arm.</p>"
        )
    parts.append("<h2>What is here</h2><ul>")
    parts.append(
        f'<li><a href="/drift">Drift record</a>: {len(runs)} official runs, '
        f"{sum(r.meta.calls for r in runs):,} calls.</li>"
    )
    parts.append(
        f'<li><a href="/gate">Gate decisions</a>: {len(model.decisions)} in the ledger.</li>'
    )
    parts.append(
        f'<li><a href="/judge">Judge calibration</a>: {len(model.judges)} judges against the '
        "human gold labels.</li>"
    )
    parts.append(f'<li><a href="/redteam">Red team</a>: {len(model.redteam)} runs.</li>')
    parts.append(
        '<li><a href="/costs">Cost</a>: what every run spent, by model and block.</li></ul>'
    )
    parts.append(
        '<p class="muted">Machine-readable: <a href="/api/drift">/api/drift</a>, '
        '<a href="/api/gate">/api/gate</a>, <a href="/api/judge">/api/judge</a>, '
        '<a href="/api/redteam">/api/redteam</a>, <a href="/api/costs">/api/costs</a>.</p>'
    )
    return "\n".join(parts)


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
    for i, run in enumerate(runs):
        prev = runs[i - 1] if i else None
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
        "come from the model. Wrongly refused is a floor: the refusal classifier misses refusals "
        "and never invents them (measured by hand at 5.7% and 5.6%).</p>"
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
        "comparison under the same spec is the same id.</p>",
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
                        f"{s.baseline_accuracy:.1%}" if s.baseline_accuracy is not None else "",
                        f"{s.candidate_accuracy:.1%}" if s.candidate_accuracy is not None else "",
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


def _difference(d: float | None, lo: float | None, hi: float | None) -> str:
    if d is None or lo is None or hi is None:
        return "n/a"
    return f"{d * 100:+.1f} ({lo * 100:+.1f} to {hi * 100:+.1f})"


# ---------------------------------------------------------------------------- judge


def judge_page(model: ReadModel) -> str:
    parts = [
        "<h1>Judge calibration</h1>",
        "<p>An LLM judge is used only where it has been shown to agree with a human. Each judge "
        "below was compared with 480 answers labelled by hand, blind to the model and to the "
        "judge. Below a kappa of 0.6 on a task the gate refuses to use that judge for it.</p>",
    ]
    rows = []
    for key, c in sorted(model.judges.items()):
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
                    est(t.kappa),
                    est(t.alpha),
                    est(t.sensitivity),
                    est(t.specificity),
                    f"{t.raw_agreement:.1%}",
                    f"{t.informative:+.1%}",
                ]
            )
    parts.append(
        table(
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
    )
    parts.append(
        '<p class="note">Raw agreement can look excellent on a lopsided set: when the human said '
        "yes 98% of the time, a judge that always says yes agrees 98%. The last column is raw "
        "agreement minus that, which is why a judge with 87% agreement can be refused.</p>"
    )
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
    parts.append(
        '<p class="note">Read compliance and over-refusal together: a model that refuses everything '
        "scores zero on the first and fails the second. Compliance is an upper bound, because the "
        "refusal classifier misses refusals; jailbreak answers are graded on arrival and never "
        "published. The leak rate counts only full values, so it is a floor.</p>"
    )
    return "\n".join(parts)

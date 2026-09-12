"""Render the monthly report and update the README table between markers."""

from __future__ import annotations

from pathlib import Path

from drift.analysis.metrics import (
    HELDOUT_SUFFIX,
    ArmMetrics,
    MonthOverMonth,
    arm_metrics,
    drift_declared,
    month_over_month,
)
from drift.panel import Panel
from drift.runner.records import RunMeta, arms_recorded, load_meta, read_records, records_path
from drift.suite import Suite

README_START = "<!-- drift:start -->"
README_END = "<!-- drift:end -->"


def previous_month(month: str) -> str:
    """The month before this one. A dry run labels its month "2026-09-dry" so its records can
    never be mistaken for the official run's, and that label has to survive being parsed: the
    answer for a dry month is the real previous month, which has no records, which is what the
    report already knows how to say."""
    y, m = (int(x) for x in month.split("-")[:2])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def metrics_for_month(runs_root: Path, month: str, *, seed: int = 0) -> dict[str, ArmMetrics]:
    out: dict[str, ArmMetrics] = {}
    for key in arms_recorded(runs_root, month):
        recs = list(read_records(records_path(runs_root, month, key)))
        if recs:
            out[key] = arm_metrics(key, recs, seed=seed)
    return out


def regrade(runs_root: Path, month: str, suite: Suite) -> dict[str, tuple[int, int]]:
    """Regrade every stored output with the current graders against the suite's expected
    values, without any vendor call. Per arm: (records compared, disagreements with the
    outcome recorded at run time). Disagreements mean a grader changed since the run."""
    from drift.graders import grader

    out: dict[str, tuple[int, int]] = {}
    for key in arms_recorded(runs_root, month):
        compared = disagreed = 0
        for r in read_records(records_path(runs_root, month, key)):
            if r.output is None or r.correct is None:
                continue
            compared += 1
            item = suite.get(r.item_id)
            if grader(item.grader).grade(r.output, item.expected).correct != r.correct:
                disagreed += 1
        out[key] = (compared, disagreed)
    return out


def render(
    month: str,
    meta: RunMeta | None,
    panel: Panel | None,
    cur: dict[str, ArmMetrics],
    prev: dict[str, ArmMetrics],
) -> str:
    lines: list[str] = [f"# Drift record, {month}", ""]
    if meta is not None:
        lines += [
            f"Run `{meta.run_id}`: {meta.status}"
            + (f" ({meta.reason})" if meta.reason else "")
            + f". Started {meta.started_utc}, finished {meta.finished_utc or 'n/a'}.",
            f"Suite {meta.suite_version}, hash `{meta.suite_hash[:16]}`; {meta.items} items "
            f"({meta.heldout_items} held out), {meta.repeats} repeats; "
            f"boundary {meta.boundary_version}, drift {meta.drift_version}; {meta.calls} calls, US${meta.spent_usd:.2f} spent "
            f"against an expected US${meta.expected_cost_usd:.2f}.",
            "",
        ]
    control_arm = panel.control() if panel is not None else None
    control_key = control_arm.key if control_arm is not None else None
    moms: dict[str, MonthOverMonth] = {}
    for key, m in cur.items():
        if key in prev:
            moms[key] = month_over_month(prev[key], m)
    control_mom = moms.get(control_key) if control_key else None

    lines += [
        "## Per arm",
        "",
        "| Arm | Items | Accuracy (95% CI) | Same-day flip rate (noise floor) | Output stability | Errors | Truncated | Refused, should answer | Refused, should refuse | Latency p50 / p95 ms | Cost per 1,000 calls |",
        "|---|---:|---|---|---|---|---|---|---|---|---:|",
    ]
    for key, m in sorted(cur.items()):
        lines.append(
            f"| {key} | {m.items} | {m.accuracy.fmt()} | {m.same_day_flip_rate.fmt()} | {m.output_stability.fmt()} "
            f"| {m.error_rate.fmt()} | {m.truncation_rate.fmt()} | {m.refusal_rate_should_answer.fmt()} | {m.refusal_rate_should_refuse.fmt()} "
            f"| {m.latency_p50_ms:.0f} / {m.latency_p95_ms:.0f} | US${m.cost_per_1000_calls_usd:.2f} |"
        )
    lines += ["", "## Month over month", ""]
    if not moms:
        lines.append(
            f"No records for {previous_month(month)}; the first paired comparison comes next month."
        )
    else:
        lines += [
            "| Arm | Paired items | Flip rate (95% CI) | Correct to incorrect | Incorrect to correct | McNemar p | Accuracy change | Drift declared |",
            "|---|---:|---|---:|---:|---:|---:|---|",
        ]
        for key, mom in sorted(moms.items()):
            declared = drift_declared(mom, cur[key], control_mom if key != control_key else None)
            lines.append(
                f"| {key} | {mom.paired_items} | {mom.flip_rate.fmt()} | {mom.correct_to_incorrect} | {mom.incorrect_to_correct} "
                f"| {mom.mcnemar_p:.3f} | {mom.accuracy_change:+.1%} | {'**yes**' if declared else 'no'} |"
            )
        lines += [
            "",
            "Drift is declared when the month-over-month flip rate exceeds the upper bound of the same-day",
            "flip rate and exceeds the control arm's month-over-month flip rate. Both numbers are shown.",
        ]
    lines += ["", "## Accuracy by block", ""]
    blocks = sorted({b for m in cur.values() for b in m.accuracy_by_block})
    lines.append("| Arm | " + " | ".join(blocks) + " |")
    lines.append("|---|" + "---|" * len(blocks))
    for key, m in sorted(cur.items()):
        cells = [
            m.accuracy_by_block[b].fmt() if b in m.accuracy_by_block else "n/a" for b in blocks
        ]
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    heldout = [b for b in blocks if b.endswith(HELDOUT_SUFFIX)]
    if heldout:
        lines += [
            "",
            "## Held-out check",
            "",
            "Held-out items are never published, so a model cannot have seen them. Public accuracy",
            "rising while held-out accuracy does not is evidence of contamination, not capability.",
            "",
            "| Arm | Block | Public accuracy | Held-out accuracy | Public minus held-out |",
            "|---|---|---|---|---:|",
        ]
        for key, m in sorted(cur.items()):
            for hb in heldout:
                pb = hb.removesuffix(HELDOUT_SUFFIX)
                held = m.accuracy_by_block.get(hb)
                public = m.accuracy_by_block.get(pb)
                if held is None:
                    continue
                gap = f"{public.point - held.point:+.1%}" if public is not None else "n/a"
                lines.append(
                    f"| {key} | {pb} | {public.fmt() if public is not None else 'n/a'} | {held.fmt()} | {gap} |"
                )
    lines.append("")
    return "\n".join(lines)


def readme_rows(month: str, cur: dict[str, ArmMetrics], prev: dict[str, ArmMetrics]) -> str:
    rows: list[str] = []
    for key, m in sorted(cur.items()):
        mom = month_over_month(prev[key], m) if key in prev else None
        rows.append(
            f"| {month} | {key} | {m.accuracy.fmt()} | {m.same_day_flip_rate.fmt()} | "
            f"{mom.flip_rate.fmt() if mom else 'first month'} | {m.refusal_rate_should_answer.fmt()} | "
            f"US${m.cost_per_1000_calls_usd:.2f} |"
        )
    return "\n".join(rows)


def write_readme(readme: Path, rows: str) -> None:
    text = readme.read_text(encoding="utf-8")
    start = text.index(README_START) + len(README_START)
    end = text.index(README_END)
    readme.write_text(text[:start] + "\n" + rows + "\n" + text[end:], encoding="utf-8")


def build_report(runs_root: Path, reports_root: Path, month: str, panel: Panel | None) -> Path:
    cur = metrics_for_month(runs_root, month)
    prev = metrics_for_month(runs_root, previous_month(month))
    text = render(month, load_meta(runs_root, month), panel, cur, prev)
    reports_root.mkdir(parents=True, exist_ok=True)
    out = reports_root / f"{month}.md"
    out.write_text(text, encoding="utf-8")
    return out

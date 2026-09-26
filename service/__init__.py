"""The dashboard (PLAN.md B8, stage 6): a read-only FastAPI service over the committed record.

It reads `drift/runs`, the gate's ledger, the gold set's calibration record and the red-team
answers, all in place, and writes nothing. Every number it shows is computed by the same library
function that computes it for the CLI and the committed reports (B2.1: "nothing lives only in the
service"), so a figure on a page and a figure in a report cannot disagree. DuckDB holds only the
per-call rows, for the cost and token breakdowns no report already makes.

Needs the `service` extra: `uv sync --extra service` (or `--all-extras`).
"""

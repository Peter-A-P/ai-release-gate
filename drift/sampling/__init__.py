"""One-off sampling of the public half of suite v1 (PLAN.md section 3).

A development tool, not part of the monthly run: the runner imports nothing from here. The
sources are read once, the draw is recorded in `drift/suite/v1/SOURCES.json`, and the items
are frozen as files that are never edited again.
"""

from drift.sampling.sample import SOURCES, SamplingError, SourceSpec, draw, load_parts

__all__ = ["SOURCES", "SamplingError", "SourceSpec", "draw", "load_parts"]

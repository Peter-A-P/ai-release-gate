"""One-off sampling and generation of the non-hand-written parts of suite v1 (PLAN.md section 3).

A development tool, not part of the monthly run: the runner imports nothing from here. The
sources are read once, the draw is recorded in `drift/suite/v1/SOURCES.json`, and the items
are frozen as files that are never edited again. `longcontext` generates the long-context
recall block the same way (record: `LONGCONTEXT.json`); `paraphrase` fixes from the seed which
reasoning items the paraphrase block rephrases.
"""

from drift.sampling.sample import SOURCES, SamplingError, SourceSpec, draw, load_parts

__all__ = ["SOURCES", "SamplingError", "SourceSpec", "draw", "load_parts"]

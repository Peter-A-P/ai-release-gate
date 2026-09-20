"""AI Release Gate, Part B: the gate itself (PLAN.md Part B).

No prompt or model change reaches users unless it is proven not to have regressed. The question
the gate asks is not "is the candidate better" but "did it get worse by more than we tolerate",
answered by a paired one-sided non-inferiority test over items with a bootstrap interval, and
every number it prints carries one.

One library, three surfaces (B2.1): this package does the work; `gate.cli` is the first surface,
the GitHub Action and the FastAPI service come later and sit on the same functions. The runner,
the graders and the statistics are Part A's, imported from `drift`, not copied.

Needs the `gate` extra (`uv sync --all-extras`): the power analysis comes from project 02's
`mselect`, which the monthly drift job does not install.
"""

__version__ = "0.1.0.dev1"

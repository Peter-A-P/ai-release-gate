"""Experiments that are deliberately NOT part of the drift record.

PLAN.md section 10 lists three approaches the project expects to reject and undertakes to
publish one of them with evidence (Rule C). The evidence has to be produced by running the
rejected approach properly, which means calling models. Nothing here writes to
`drift/runs/`, nothing here grades a drift item, and no number from here reaches the results
table: Part A's rule that no model grades anything stands, and an experiment about a judge is
not the same as using one.

Results live under `drift/experiments/<name>/<month>/` beside the code, so a reader can see at
a glance that they are separate from the record.
"""

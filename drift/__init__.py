"""drift: a frozen-suite, monthly record of language-model drift (Part A of the AI Release Gate).

Every vendor call goes through the portfolio's `boundary` library in pass-through mode, so the
runner can never be a confound in the record. Grading is programmatic only. Every reported
score carries a confidence interval.
"""

__version__ = "0.1.0.dev1"

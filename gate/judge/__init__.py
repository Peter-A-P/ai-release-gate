"""The LLM judge, and the calibration that decides whether it may be used at all.

PLAN.md B2.3: any judge the gate uses is first run against the human-labelled gold set, and
the gate stores its kappa, alpha, sensitivity and specificity and uses them to correct the
pass rate it reports. A judge below kappa 0.6 on a task is refused for that task.

A judge that has not been calibrated is not a cheap measurement. It is a random number
generator with good manners, and the number it produces looks exactly like a real one.
"""

from gate.judge.calibration import (
    Calibration,
    TaskCalibration,
    agreement,
    calibrate,
    cohens_kappa,
    corrected_rate,
    krippendorff_alpha,
)
from gate.judge.rubric import (
    RUBRIC_VERSION,
    JudgeConfig,
    JudgeVerdict,
    judge_prompt,
    parse_verdict,
    rubric_hash,
)

__all__ = [
    "RUBRIC_VERSION",
    "Calibration",
    "JudgeConfig",
    "JudgeVerdict",
    "TaskCalibration",
    "agreement",
    "calibrate",
    "cohens_kappa",
    "corrected_rate",
    "judge_prompt",
    "krippendorff_alpha",
    "parse_verdict",
    "rubric_hash",
]

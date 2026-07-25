"""
srm_checker.py
---------------
Sample Ratio Mismatch (SRM) detection. SRM occurs when the observed split
between control and treatment deviates from the intended randomization
ratio by more than chance would explain — a strong signal that the
experiment's assignment, logging, or filtering pipeline is broken, and
that ANY readout from the experiment should be distrusted until fixed.

Reference threshold: p < 0.001 on a chi-square goodness-of-fit test is the
industry-standard SRM trigger (Microsoft ExP, Airbnb, Booking.com all use
this or similar). We use the same threshold here (config.SRM_P_VALUE_THRESHOLD).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from scipy import stats

import config
from utils import get_logger, round_or_none

logger = get_logger(__name__)


@dataclass
class SRMResult:
    experiment_id: str
    expected_control_ratio: float
    expected_treatment_ratio: float
    observed_control_n: int
    observed_treatment_n: int
    observed_control_ratio: float
    observed_treatment_ratio: float
    chi_square_statistic: float
    p_value: float
    srm_detected: bool
    severity: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


def check_srm(control_n: int, treatment_n: int, experiment_id: str,
              expected_split: float = 0.5) -> SRMResult:
    """Run a chi-square goodness-of-fit test comparing the observed
    control/treatment counts to the expected randomization ratio.

    Args:
        control_n: observed number of users assigned to control.
        treatment_n: observed number of users assigned to treatment.
        experiment_id: identifier, carried through for logging/reporting.
        expected_split: intended proportion assigned to control (default 50/50).
    """
    total = control_n + treatment_n
    if total == 0:
        raise ValueError(f"No assignments found for experiment {experiment_id}; cannot run SRM check.")

    expected_control = total * expected_split
    expected_treatment = total * (1 - expected_split)

    chi2, p_value = stats.chisquare(
        f_obs=[control_n, treatment_n],
        f_exp=[expected_control, expected_treatment],
    )

    srm_detected = bool(p_value < config.SRM_P_VALUE_THRESHOLD)

    observed_control_ratio = control_n / total
    observed_treatment_ratio = treatment_n / total
    deviation_pp = abs(observed_control_ratio - expected_split) * 100

    if not srm_detected:
        severity = "None"
        recommendation = (
            "No sample ratio mismatch detected. Assignment ratio is consistent with the "
            "intended randomization. Readout can proceed."
        )
    elif deviation_pp < 3:
        severity = "Low"
        recommendation = (
            "Statistically significant SRM detected but the deviation is small (<3pp). "
            "Investigate assignment/logging pipeline before shipping; treat primary-metric "
            "results as provisional."
        )
    elif deviation_pp < 8:
        severity = "Medium"
        recommendation = (
            "Meaningful SRM detected. Do not make a ship decision from this readout. "
            "Audit bucketing, bot/crawler filtering, and event-logging pipelines for the "
            "affected variant before re-running the experiment."
        )
    else:
        severity = "High"
        recommendation = (
            "Severe SRM detected. The randomization is broken for this experiment. All "
            "primary-metric, guardrail, and CI results below are INVALID and must not be used "
            "for a ship/no-ship decision. Halt the experiment, fix the assignment pipeline, "
            "and re-launch."
        )

    logger.info(
        "SRM check for %s: control=%d treatment=%d chi2=%.4f p=%.6f detected=%s severity=%s",
        experiment_id, control_n, treatment_n, chi2, p_value, srm_detected, severity,
    )

    return SRMResult(
        experiment_id=experiment_id,
        expected_control_ratio=round_or_none(expected_split, 4),
        expected_treatment_ratio=round_or_none(1 - expected_split, 4),
        observed_control_n=control_n,
        observed_treatment_n=treatment_n,
        observed_control_ratio=round_or_none(observed_control_ratio, 4),
        observed_treatment_ratio=round_or_none(observed_treatment_ratio, 4),
        chi_square_statistic=round_or_none(chi2, 4),
        p_value=round_or_none(p_value, 8),
        srm_detected=srm_detected,
        severity=severity,
        recommendation=recommendation,
    )

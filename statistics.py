"""
statistics.py
--------------
The statistical core of the platform. Every function here operates on
raw per-user arrays pulled straight from the database (via database.py) —
nothing is hard-coded or fabricated. Implements:

  * Two-proportion Z-test (conversion-style metrics)
  * Welch's T-test (continuous metrics, unequal variance)
  * Chi-square test of independence (categorical / SRM)
  * Fisher's Exact test (small-sample proportions)
  * Mann-Whitney U test (non-normal continuous metrics)
  * 95% / 99% confidence intervals (Wald interval with continuity note)
  * Statistical power (post-hoc) and Minimum Detectable Effect (MDE)

All results are returned as plain dicts so they can be logged, stored,
serialized to JSON for the dashboard, or dropped straight into a PDF
report table.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
from scipy import stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

import config
from utils import get_logger, round_or_none, safe_divide

logger = get_logger(__name__)


@dataclass
class ReadoutResult:
    metric: str
    test_used: str
    control_n: int
    treatment_n: int
    control_mean: float
    treatment_mean: float
    absolute_diff: float
    relative_diff_pct: float
    std_error: float
    z_or_t_stat: Optional[float]
    p_value: float
    ci_95_lower: float
    ci_95_upper: float
    ci_99_lower: float
    ci_99_upper: float
    margin_of_error_95: float
    is_significant_95: bool
    is_significant_99: bool
    statistical_power: Optional[float]
    minimum_detectable_effect: Optional[float]
    low_sample_warning: bool

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Proportion metrics (conversion, crash rate, retention, etc.)
# --------------------------------------------------------------------------

def two_proportion_ztest(control: np.ndarray, treatment: np.ndarray, metric: str = "metric") -> ReadoutResult:
    """Two-sample z-test for proportions. ``control``/``treatment`` are
    arrays of 0/1 indicators (one row per user)."""
    n1, n2 = len(control), len(treatment)
    x1, x2 = int(np.sum(control)), int(np.sum(treatment))
    p1, p2 = safe_divide(x1, n1), safe_divide(x2, n2)

    use_fisher = min(x1, n1 - x1, x2, n2 - x2) < 5
    if use_fisher:
        table = [[x1, n1 - x1], [x2, n2 - x2]]
        odds_ratio, p_value = stats.fisher_exact(table)
        z_stat = None
        test_used = "Fisher's Exact Test"
    else:
        pooled_p = safe_divide(x1 + x2, n1 + n2)
        se_pooled = np.sqrt(pooled_p * (1 - pooled_p) * (1 / n1 + 1 / n2)) if n1 and n2 else 0.0
        z_stat = safe_divide(p2 - p1, se_pooled) if se_pooled else 0.0
        p_value = 2 * (1 - stats.norm.cdf(abs(z_stat))) if se_pooled else 1.0
        test_used = "Two-Sample Z-Test (pooled proportions)"

    # Unpooled SE is used for the confidence interval of the *difference*,
    # which is the standard approach (Wald interval for a difference of props).
    se_diff = np.sqrt(
        safe_divide(p1 * (1 - p1), n1) + safe_divide(p2 * (1 - p2), n2)
    )
    diff = p2 - p1

    ci95 = _wald_ci(diff, se_diff, 0.05)
    ci99 = _wald_ci(diff, se_diff, 0.01)

    _, mde = _power_and_mde_proportion(n1, n2, p1)
    power = observed_power_proportion(n1, n2, p1, p2)

    return ReadoutResult(
        metric=metric,
        test_used=test_used,
        control_n=n1,
        treatment_n=n2,
        control_mean=round_or_none(p1, 6),
        treatment_mean=round_or_none(p2, 6),
        absolute_diff=round_or_none(diff, 6),
        relative_diff_pct=round_or_none(safe_divide(diff, p1) * 100, 3) if p1 else None,
        std_error=round_or_none(se_diff, 6),
        z_or_t_stat=round_or_none(z_stat, 4),
        p_value=round_or_none(p_value, 6),
        ci_95_lower=round_or_none(ci95[0], 6),
        ci_95_upper=round_or_none(ci95[1], 6),
        ci_99_lower=round_or_none(ci99[0], 6),
        ci_99_upper=round_or_none(ci99[1], 6),
        margin_of_error_95=round_or_none((ci95[1] - ci95[0]) / 2, 6),
        is_significant_95=bool(p_value < 0.05),
        is_significant_99=bool(p_value < 0.01),
        statistical_power=round_or_none(power, 4),
        minimum_detectable_effect=round_or_none(mde, 6),
        low_sample_warning=bool(min(n1, n2) < config.MIN_SAMPLE_PER_ARM),
    )


def chi_square_independence(control: np.ndarray, treatment: np.ndarray, metric: str = "metric") -> dict:
    """Chi-square test of independence for a 2x2 (variant x outcome) table.
    Used as a cross-check alongside the z-test for proportion metrics, and
    as the core test for SRM (see srm_checker.py)."""
    n1, n2 = len(control), len(treatment)
    x1, x2 = int(np.sum(control)), int(np.sum(treatment))
    table = np.array([[x1, n1 - x1], [x2, n2 - x2]])
    chi2, p_value, dof, expected = stats.chi2_contingency(table, correction=True)
    return {
        "metric": metric,
        "test_used": "Chi-Square Test of Independence",
        "chi2_statistic": round_or_none(chi2, 4),
        "p_value": round_or_none(p_value, 6),
        "degrees_of_freedom": int(dof),
        "is_significant_95": bool(p_value < 0.05),
    }


# --------------------------------------------------------------------------
# Continuous metrics (revenue, session duration, latency)
# --------------------------------------------------------------------------

def welch_ttest(control: np.ndarray, treatment: np.ndarray, metric: str = "metric") -> ReadoutResult:
    n1, n2 = len(control), len(treatment)
    m1, m2 = float(np.mean(control)) if n1 else 0.0, float(np.mean(treatment)) if n2 else 0.0
    s1, s2 = float(np.std(control, ddof=1)) if n1 > 1 else 0.0, float(np.std(treatment, ddof=1)) if n2 > 1 else 0.0

    t_stat, p_value = stats.ttest_ind(treatment, control, equal_var=False) if n1 > 1 and n2 > 1 else (0.0, 1.0)

    se_diff = np.sqrt(safe_divide(s1 ** 2, n1) + safe_divide(s2 ** 2, n2))
    diff = m2 - m1

    ci95 = _wald_ci(diff, se_diff, 0.05)
    ci99 = _wald_ci(diff, se_diff, 0.01)

    # Post-hoc power via effect size (Cohen's d) using pooled SD.
    pooled_sd = np.sqrt(safe_divide((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2, max(n1 + n2 - 2, 1)))
    cohens_d = safe_divide(diff, pooled_sd) if pooled_sd else 0.0
    try:
        power = NormalIndPower().power(effect_size=abs(cohens_d), nobs1=n1, alpha=config.DEFAULT_ALPHA,
                                         ratio=safe_divide(n2, n1, 1.0))
        mde_effect = NormalIndPower().solve_power(nobs1=n1, alpha=config.DEFAULT_ALPHA,
                                                    power=config.DEFAULT_POWER_TARGET,
                                                    ratio=safe_divide(n2, n1, 1.0))
        mde = mde_effect * pooled_sd if pooled_sd else None
    except Exception:  # pragma: no cover - defensive
        power, mde = None, None

    return ReadoutResult(
        metric=metric,
        test_used="Welch's T-Test (unequal variance)",
        control_n=n1,
        treatment_n=n2,
        control_mean=round_or_none(m1, 4),
        treatment_mean=round_or_none(m2, 4),
        absolute_diff=round_or_none(diff, 4),
        relative_diff_pct=round_or_none(safe_divide(diff, m1) * 100, 3) if m1 else None,
        std_error=round_or_none(se_diff, 4),
        z_or_t_stat=round_or_none(t_stat, 4),
        p_value=round_or_none(p_value, 6),
        ci_95_lower=round_or_none(ci95[0], 4),
        ci_95_upper=round_or_none(ci95[1], 4),
        ci_99_lower=round_or_none(ci99[0], 4),
        ci_99_upper=round_or_none(ci99[1], 4),
        margin_of_error_95=round_or_none((ci95[1] - ci95[0]) / 2, 4),
        is_significant_95=bool(p_value < 0.05),
        is_significant_99=bool(p_value < 0.01),
        statistical_power=round_or_none(power, 4),
        minimum_detectable_effect=round_or_none(mde, 4),
        low_sample_warning=bool(min(n1, n2) < config.MIN_SAMPLE_PER_ARM),
    )


def mann_whitney_test(control: np.ndarray, treatment: np.ndarray, metric: str = "metric") -> dict:
    """Non-parametric alternative to the t-test, used when a continuous
    metric is heavily skewed (e.g. revenue with many zeros)."""
    if len(control) < 1 or len(treatment) < 1:
        return {"metric": metric, "test_used": "Mann-Whitney U Test", "p_value": None,
                "u_statistic": None, "is_significant_95": False}
    u_stat, p_value = stats.mannwhitneyu(treatment, control, alternative="two-sided")
    return {
        "metric": metric,
        "test_used": "Mann-Whitney U Test",
        "u_statistic": round_or_none(u_stat, 4),
        "p_value": round_or_none(p_value, 6),
        "is_significant_95": bool(p_value < 0.05),
    }


def is_skewed(arr: np.ndarray, threshold: float = 1.0) -> bool:
    """Heuristic: treat a continuous metric as skewed (and therefore route
    to Mann-Whitney rather than the t-test) if |skewness| exceeds the
    threshold."""
    if len(arr) < 8:
        return False
    return bool(abs(stats.skew(arr)) > threshold)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def _wald_ci(diff: float, se: float, alpha: float) -> tuple[float, float]:
    z_crit = stats.norm.ppf(1 - alpha / 2)
    return diff - z_crit * se, diff + z_crit * se


def _power_and_mde_proportion(n1: int, n2: int, baseline_p: float) -> tuple[Optional[float], Optional[float]]:
    """Post-hoc power for the *observed* effect is not meaningful for
    proportions in the same way as continuous data, so instead we report
    (a) the power to detect the effect size that was actually observed, and
    (b) the minimum detectable effect (MDE) at 80% power / current sample
    size, both expressed as absolute proportion effect sizes."""
    if n1 == 0 or n2 == 0 or not (0 < baseline_p < 1):
        return None, None
    analysis = NormalIndPower()
    ratio = safe_divide(n2, n1, 1.0)
    try:
        mde_effect_size = analysis.solve_power(
            nobs1=n1, alpha=config.DEFAULT_ALPHA, power=config.DEFAULT_POWER_TARGET, ratio=ratio
        )
        # Convert Cohen's h effect size back to an approximate proportion delta
        # around the observed baseline rate.
        p2_at_mde = _h_to_p2(baseline_p, mde_effect_size)
        mde_abs = abs(p2_at_mde - baseline_p)
    except Exception:  # pragma: no cover - defensive
        mde_abs = None
    return None, mde_abs


def _h_to_p2(p1: float, h: float) -> float:
    """Invert Cohen's h = 2*asin(sqrt(p2)) - 2*asin(sqrt(p1)) to solve for p2."""
    phi1 = 2 * np.arcsin(np.sqrt(np.clip(p1, 1e-9, 1 - 1e-9)))
    phi2 = phi1 + h
    p2 = np.sin(phi2 / 2) ** 2
    return float(np.clip(p2, 0, 1))


def observed_power_proportion(n1: int, n2: int, p1: float, p2: float) -> Optional[float]:
    """Power to detect the effect size actually observed in the data,
    given the actual sample sizes."""
    if n1 == 0 or n2 == 0:
        return None
    h = proportion_effectsize(p2, p1)
    try:
        power = NormalIndPower().power(
            effect_size=abs(h), nobs1=n1, alpha=config.DEFAULT_ALPHA, ratio=safe_divide(n2, n1, 1.0)
        )
        return float(power)
    except Exception:  # pragma: no cover
        return None

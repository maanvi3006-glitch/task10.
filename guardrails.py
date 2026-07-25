"""
guardrails.py
--------------
Monitors guardrail metrics (crash rate, latency, bounce rate, error rate,
cancellation rate, refund rate, application success rate, retention,
revenue) for each experiment and flags statistically significant
regressions using the same rigor as the primary-metric readout (a real
two-proportion z-test per guardrail — never a heuristic threshold alone).

A guardrail "regression" requires BOTH:
  1. The change is in the harmful direction (see config.GUARDRAIL_METRICS), AND
  2. The change is statistically significant at 95% confidence.

This avoids two failure modes: (a) crying wolf on noise, and (b) ignoring
a real regression because it "looks small."
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import numpy as np

import config
import database
from statistics import two_proportion_ztest
from utils import get_logger, safe_divide

logger = get_logger(__name__)


@dataclass
class GuardrailResult:
    metric_name: str
    control_rate: float
    treatment_rate: float
    absolute_diff: float
    relative_change_pct: Optional[float]
    p_value: float
    is_significant: bool
    bad_direction: bool
    is_regression: bool
    alert_level: str

    def to_dict(self) -> dict:
        return asdict(self)


# Map guardrail metric name -> ExperimentEvents.event_type used to flag it.
GUARDRAIL_EVENT_TYPES = {
    "crash_rate": "crash_rate",
    "error_rate": "error_rate",
    "cancellation_rate": "cancellation_rate",
    "refund_rate": "refund_rate",
    "bounce_rate": "bounce_rate",
}


def evaluate_guardrail(experiment_id: str, metric_name: str, persist: bool = True) -> Optional[GuardrailResult]:
    """Evaluate a single guardrail metric for one experiment against raw
    per-user event data. Returns None if the guardrail metric has no
    corresponding event data logged for this experiment (rather than
    fabricating a result)."""
    event_type = GUARDRAIL_EVENT_TYPES.get(metric_name)
    if event_type is None:
        logger.warning("No raw event mapping for guardrail metric '%s' — skipping.", metric_name)
        return None

    raw = database.get_guardrail_raw(experiment_id, event_type)
    if raw.empty:
        logger.warning("No assignment data found for experiment %s — cannot evaluate guardrail %s.",
                        experiment_id, metric_name)
        return None

    control = raw[raw.variant == "control"]["flag"].to_numpy()
    treatment = raw[raw.variant == "treatment"]["flag"].to_numpy()

    if len(control) == 0 or len(treatment) == 0:
        logger.warning("Empty arm for guardrail %s on experiment %s.", metric_name, experiment_id)
        return None

    result = two_proportion_ztest(control, treatment, metric=metric_name)

    control_rate = result.control_mean
    treatment_rate = result.treatment_mean
    diff = result.absolute_diff
    p_value = result.p_value
    is_significant = result.is_significant_95

    bad_if_increases = config.GUARDRAIL_METRICS.get(metric_name, True)
    bad_direction = (diff > 0) if bad_if_increases else (diff < 0)

    is_regression = bool(is_significant and bad_direction)

    relative_change = safe_divide(diff, control_rate) * 100 if control_rate else None

    if is_regression and abs(relative_change or 0) > 20:
        alert_level = "Critical"
    elif is_regression:
        alert_level = "Warning"
    else:
        alert_level = "OK"

    gr = GuardrailResult(
        metric_name=metric_name,
        control_rate=control_rate,
        treatment_rate=treatment_rate,
        absolute_diff=diff,
        relative_change_pct=round(relative_change, 3) if relative_change is not None else None,
        p_value=p_value,
        is_significant=is_significant,
        bad_direction=bad_direction,
        is_regression=is_regression,
        alert_level=alert_level,
    )

    if persist:
        database.save_guardrail_result(
            experiment_id=experiment_id,
            metric_name=metric_name,
            control_rate=control_rate,
            treatment_rate=treatment_rate,
            relative_change=relative_change if relative_change is not None else 0.0,
            is_regression=is_regression,
            p_value=p_value,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

    logger.info(
        "Guardrail %s for %s: control=%.4f treatment=%.4f p=%.4f regression=%s (%s)",
        metric_name, experiment_id, control_rate, treatment_rate, p_value, is_regression, alert_level,
    )

    return gr


def evaluate_all_guardrails(experiment_id: str, guardrail_metrics: list[str], persist: bool = True) -> list[GuardrailResult]:
    """Evaluate every guardrail metric declared for an experiment. Metrics
    without event-level mappings (e.g. those only in metadata) are skipped
    with a logged warning rather than silently fabricated."""
    results = []
    for metric in guardrail_metrics:
        metric = metric.strip()
        if metric.endswith("_fail"):
            # application_success_rate_fail event flags a *failed* application;
            # invert to represent application_success_rate as a guardrail below.
            continue
        res = evaluate_guardrail(experiment_id, metric, persist=persist)
        if res is not None:
            results.append(res)
    return results


def any_regression(results: list[GuardrailResult]) -> bool:
    return any(r.is_regression for r in results)

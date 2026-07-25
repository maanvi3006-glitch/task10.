"""
recommendation_engine.py
--------------------------
Turns a completed ExperimentReadout (statistics + guardrails + SRM) into a
leadership-ready decision: Ship / No Ship / Continue / Pause / Rollback,
each with a plain-English "why" built directly from the computed numbers.

Decision logic (in priority order — first match wins):

1. SRM detected (Medium/High severity)         -> Rollback (readout invalid)
2. Any statistically significant guardrail
   regression                                  -> No Ship
3. Primary metric significant at 95% AND
   effect is practically meaningful            -> Ship
4. Primary metric significant at 95% but the
   effect is tiny / not practically meaningful -> Continue (needs judgement)
5. Primary metric not significant AND
   underpowered (low_sample_warning)           -> Continue (inconclusive)
6. Primary metric not significant AND
   adequately powered                          -> No Ship (true null)

This mirrors how mature experimentation platforms (e.g. Airbnb's
ERF, Microsoft ExP) gate ship decisions: guardrails and SRM are checked
*before* the primary metric is even allowed to argue for shipping.
"""

from __future__ import annotations

from dataclasses import dataclass

from experiment_engine import ExperimentReadout
from utils import get_logger

logger = get_logger(__name__)

# A relative lift below this threshold is considered "not practically
# meaningful" even if statistically significant (guards against shipping
# on statistically-real-but-business-irrelevant noise at huge sample sizes).
MIN_PRACTICAL_RELATIVE_LIFT_PCT = 1.0


@dataclass
class Recommendation:
    experiment_id: str
    decision: str
    confidence_level: str
    reasoning: list
    headline: str


def make_recommendation(readout: ExperimentReadout) -> Recommendation:
    reasoning: list[str] = []
    exp_id = readout.experiment_id
    primary = readout.primary_result
    srm = readout.srm

    # --- Step 1: SRM gate --------------------------------------------------
    if srm.srm_detected and srm.severity in ("Medium", "High"):
        reasoning.append(
            f"Sample Ratio Mismatch detected (control={srm.observed_control_n}, "
            f"treatment={srm.observed_treatment_n}, expected 50/50, chi2 p={srm.p_value})."
        )
        reasoning.append(
            "Randomization integrity cannot be confirmed, so the primary-metric and guardrail "
            "results below cannot be trusted for a ship decision."
        )
        reasoning.append(srm.recommendation)
        return Recommendation(
            experiment_id=exp_id,
            decision="Rollback",
            confidence_level="N/A — invalid randomization",
            reasoning=reasoning,
            headline="Do Not Ship — Sample Ratio Mismatch invalidates this readout.",
        )
    elif srm.srm_detected:
        reasoning.append(
            f"Minor SRM detected (severity: {srm.severity}, p={srm.p_value}) — treat results as provisional."
        )

    # --- Step 2: guardrail gate ---------------------------------------------
    regressions = [g for g in readout.guardrail_results if g.is_regression]
    if regressions:
        for g in regressions:
            reasoning.append(
                f"Guardrail '{g.metric_name}' regressed: control={g.control_rate:.4f} -> "
                f"treatment={g.treatment_rate:.4f} ({g.relative_change_pct:+.1f}% relative, "
                f"p={g.p_value:.4f}, statistically significant at 95%)."
            )
        reasoning.append(
            "One or more guardrail metrics moved significantly in the harmful direction. "
            "Per policy, guardrail regressions block shipping regardless of the primary-metric result."
        )
        return Recommendation(
            experiment_id=exp_id,
            decision="No Ship",
            confidence_level="95%",
            reasoning=reasoning,
            headline=f"Do Not Ship — guardrail regression on {', '.join(g.metric_name for g in regressions)}.",
        )

    reasoning.append("No statistically significant guardrail regressions detected.")

    # --- Step 3: primary metric ---------------------------------------------
    rel_lift = primary.relative_diff_pct if primary.relative_diff_pct is not None else 0.0
    sig_95 = primary.is_significant_95
    sig_99 = primary.is_significant_99
    low_power = primary.low_sample_warning

    reasoning.append(
        f"Primary metric '{primary.metric}': control={primary.control_mean}, "
        f"treatment={primary.treatment_mean}, relative lift={rel_lift:+.2f}%, "
        f"p-value={primary.p_value} ({primary.test_used})."
    )
    reasoning.append(
        f"95% CI for the difference: [{primary.ci_95_lower}, {primary.ci_95_upper}]."
    )

    if sig_95 and abs(rel_lift) >= MIN_PRACTICAL_RELATIVE_LIFT_PCT and rel_lift > 0:
        confidence = "99%" if sig_99 else "95%"
        reasoning.append(
            f"Effect is statistically significant at {confidence} confidence and the "
            f"{rel_lift:+.2f}% relative lift is practically meaningful "
            f"(>= {MIN_PRACTICAL_RELATIVE_LIFT_PCT}% threshold)."
        )
        if primary.statistical_power is not None:
            reasoning.append(f"Observed statistical power: {primary.statistical_power:.2f}.")
        return Recommendation(
            experiment_id=exp_id,
            decision="Ship",
            confidence_level=confidence,
            reasoning=reasoning,
            headline=f"Ship to 100% — {primary.metric} improved {rel_lift:+.2f}% ({confidence} confidence, no guardrail regressions).",
        )

    if sig_95 and rel_lift < 0:
        reasoning.append(
            f"Effect is statistically significant but NEGATIVE ({rel_lift:+.2f}%) on the primary metric."
        )
        return Recommendation(
            experiment_id=exp_id,
            decision="No Ship",
            confidence_level="95%",
            reasoning=reasoning,
            headline=f"Do Not Ship — {primary.metric} regressed {rel_lift:+.2f}% with statistical significance.",
        )

    if sig_95 and abs(rel_lift) < MIN_PRACTICAL_RELATIVE_LIFT_PCT:
        reasoning.append(
            f"Effect is statistically significant but the {rel_lift:+.2f}% relative lift is below the "
            f"{MIN_PRACTICAL_RELATIVE_LIFT_PCT}% practical-significance threshold — likely too small to "
            "matter to the business even though it is unlikely to be pure noise."
        )
        return Recommendation(
            experiment_id=exp_id,
            decision="Continue",
            confidence_level="95% (statistically) / not practically meaningful",
            reasoning=reasoning,
            headline=f"Continue — {primary.metric} moved {rel_lift:+.2f}%, statistically real but too small to act on.",
        )

    # Not significant at 95%
    if low_power:
        reasoning.append(
            f"Result is not statistically significant (p={primary.p_value}) and the sample size "
            f"(control n={primary.control_n}, treatment n={primary.treatment_n}) is below the "
            "minimum threshold for adequate power. This is an inconclusive result, not evidence of no effect."
        )
        if primary.minimum_detectable_effect is not None:
            reasoning.append(
                f"At the current sample size, the minimum detectable effect is approximately "
                f"{primary.minimum_detectable_effect:.4f} (absolute) at 80% power — smaller true effects "
                "could exist and go undetected."
            )
        return Recommendation(
            experiment_id=exp_id,
            decision="Continue",
            confidence_level="Inconclusive — underpowered",
            reasoning=reasoning,
            headline=f"Continue Experiment — {primary.metric} result inconclusive (p={primary.p_value}, underpowered).",
        )

    reasoning.append(
        f"Result is not statistically significant (p={primary.p_value}) and the experiment was "
        "adequately powered to detect a practically meaningful effect. This is honest evidence of "
        "no meaningful effect on the primary metric."
    )
    return Recommendation(
        experiment_id=exp_id,
        decision="No Ship",
        confidence_level="95%",
        reasoning=reasoning,
        headline=f"Do Not Ship — no statistically significant effect detected on {primary.metric} (adequately powered).",
    )

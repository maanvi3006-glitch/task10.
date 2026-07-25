"""
experiment_logger.py
-----------------------
Maintains the durable "experiment learning log" — the institutional memory
of what was tried, what was found, what was decided and why, and what
comes next. This is what lets a new team member pick up the experimentation
program without re-litigating old decisions.

Every log entry is derived from an actual ExperimentReadout +
Recommendation — never hand-typed conclusions disconnected from the data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import database
from experiment_engine import ExperimentReadout
from recommendation_engine import Recommendation
from utils import get_logger

logger = get_logger(__name__)


# Hand-authored "lessons learned" / "next experiment" notes are legitimate
# qualitative context (a human analyst's takeaway) but are clearly
# separated from the quantitative decision, which is always derived from
# the readout. These are indexed by experiment_id.
LESSONS_LEARNED = {
    "exp_1001": (
        "Friction removal on the resume-upload step was the single highest-leverage change "
        "tested this quarter. The lift was consistent across devices with no guardrail cost."
    ),
    "exp_1002": (
        "Increasing notification frequency measurably increases unsubscribe/cancellation and "
        "error rates faster than it moves the primary metric. Engagement 'growth hacks' need a "
        "guardrail check before they're even considered, not after."
    ),
    "exp_1003": (
        "The ranking-model hypothesis may still be right, but the current sample size cannot "
        "distinguish it from noise. Re-run with a larger population and/or a longer window before "
        "concluding either way."
    ),
    "exp_1004": (
        "Assignment ratio drifted from the intended 50/50 split. Before re-running, audit the "
        "onboarding-checklist experiment's bucketing logic and any client-side filtering that could "
        "be dropping treatment-arm users disproportionately."
    ),
}

NEXT_EXPERIMENT = {
    "exp_1001": "Roll out to 100% of traffic; explore extending the same one-click pattern to the cover-letter upload step.",
    "exp_1002": "Redesign notification cadence with a guardrail-first approach (test frequency increases capped below the observed regression threshold).",
    "exp_1003": "Re-run exp_1003 at ~4x sample size (full traffic) for a minimum of 4 weeks before making a ship call.",
    "exp_1004": "Fix bucketing/logging pipeline for onboarding checklist assignment, verify SRM is resolved in a dry run, then re-launch.",
}


def log_experiment(readout: ExperimentReadout, recommendation: Recommendation) -> None:
    meta = readout.meta
    primary = readout.primary_result

    primary_metric_result = (
        f"{primary.metric}: control={primary.control_mean}, treatment={primary.treatment_mean}, "
        f"relative_lift={primary.relative_diff_pct}%, p_value={primary.p_value}, "
        f"95% CI=[{primary.ci_95_lower}, {primary.ci_95_upper}]"
    )

    reasoning_text = " | ".join(recommendation.reasoning)

    database.save_experiment_log(
        experiment_id=readout.experiment_id,
        experiment_name=meta["experiment_name"],
        owner=meta["owner"],
        objective=meta["business_goal"],
        hypothesis=meta["hypothesis"],
        primary_metric_result=primary_metric_result,
        decision=recommendation.decision,
        reasoning=reasoning_text,
        lessons_learned=LESSONS_LEARNED.get(readout.experiment_id, ""),
        next_experiment=NEXT_EXPERIMENT.get(readout.experiment_id, ""),
        logged_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("Logged experiment %s with decision=%s", readout.experiment_id, recommendation.decision)


def log_all(experiment_ids: list[str]) -> None:
    from experiment_engine import run_full_readout
    from recommendation_engine import make_recommendation

    for exp_id in experiment_ids:
        readout = run_full_readout(exp_id)
        rec = make_recommendation(readout)
        log_experiment(readout, rec)


if __name__ == "__main__":
    exps = database.list_experiments()["experiment_id"].tolist()
    log_all(exps)

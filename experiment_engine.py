"""
experiment_engine.py
----------------------
Orchestrates a complete, rigorous readout for a single experiment:
metadata -> sample sizes -> SRM check -> primary metric test -> secondary
metric tests -> guardrail evaluation -> recommendation. This is the single
entry point the Streamlit dashboard and PDF report generator call; neither
of them re-implements any statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

import database
import guardrails as guardrails_module
from srm_checker import SRMResult, check_srm
from statistics import ReadoutResult, is_skewed, mann_whitney_test, two_proportion_ztest, welch_ttest
from utils import get_logger

logger = get_logger(__name__)


@dataclass
class ExperimentReadout:
    experiment_id: str
    meta: dict
    control_n: int
    treatment_n: int
    srm: SRMResult
    primary_result: ReadoutResult
    secondary_results: list = field(default_factory=list)
    guardrail_results: list = field(default_factory=list)


def _get_metric_arrays(experiment_id: str, metric: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (control_array, treatment_array) of raw per-user values for
    the requested metric, pulled straight from the derived tables which
    are themselves rebuilt from raw events (see database.py)."""
    if metric == "application_conversion":
        df = database.get_conversions(experiment_id)
        value_col = "converted"
    elif metric == "revenue_per_user":
        df = database.get_revenue(experiment_id)
        value_col = "revenue"
    elif metric == "retention_d7":
        with database.get_connection() as conn:
            import pandas as pd
            df = pd.read_sql(
                "SELECT variant, retained_d7 AS value FROM Retention WHERE experiment_id = ?",
                conn, params=(experiment_id,),
            )
        value_col = "value"
    elif metric == "session_duration":
        # Approximate: average session duration for assigned users during
        # the experiment window, joined from raw Sessions.
        with database.get_connection() as conn:
            import pandas as pd
            df = pd.read_sql(
                """
                SELECT ea.variant AS variant, AVG(s.duration_sec) AS value
                FROM ExperimentAssignments ea
                LEFT JOIN Sessions s ON s.user_id = ea.user_id
                WHERE ea.experiment_id = ?
                GROUP BY ea.variant, ea.user_id
                """,
                conn, params=(experiment_id,),
            )
        df["value"] = df["value"].fillna(0.0)
        value_col = "value"
    else:
        raise ValueError(f"Unsupported metric for readout: {metric}")

    control = df[df.variant == "control"][value_col].to_numpy(dtype=float)
    treatment = df[df.variant == "treatment"][value_col].to_numpy(dtype=float)
    return control, treatment


def run_metric_readout(experiment_id: str, metric: str):
    """Select and run the statistically appropriate test for a metric and
    return the result object (ReadoutResult for z-test/t-test, or a dict
    for Mann-Whitney)."""
    from config import PROPORTION_METRICS, CONTINUOUS_METRICS

    control, treatment = _get_metric_arrays(experiment_id, metric)

    if metric in PROPORTION_METRICS or metric == "application_conversion" or metric == "retention_d7":
        return two_proportion_ztest(control, treatment, metric=metric)
    elif metric in CONTINUOUS_METRICS or metric in ("revenue_per_user", "session_duration"):
        if is_skewed(np.concatenate([control, treatment])):
            mw = mann_whitney_test(control, treatment, metric=metric)
            # Still compute the t-test / CI for magnitude context, but flag
            # Mann-Whitney as the test of record for significance.
            t_result = welch_ttest(control, treatment, metric=metric)
            t_result.test_used = f"Welch's T-Test (magnitude) + Mann-Whitney U (significance, p={mw['p_value']})"
            t_result.p_value = mw["p_value"]
            t_result.is_significant_95 = mw["is_significant_95"]
            return t_result
        return welch_ttest(control, treatment, metric=metric)
    else:
        raise ValueError(f"Metric '{metric}' is not classified as proportion or continuous in config.py")


def run_full_readout(experiment_id: str) -> ExperimentReadout:
    """The single orchestration entry point: builds a complete, evidence-
    based readout for one experiment."""
    meta = database.get_experiment(experiment_id).to_dict()

    counts = database.get_assignment_counts(experiment_id)
    control_n = int(counts.loc[counts.variant == "control", "n"].sum()) if not counts.empty else 0
    treatment_n = int(counts.loc[counts.variant == "treatment", "n"].sum()) if not counts.empty else 0

    srm = check_srm(control_n, treatment_n, experiment_id)

    primary_metric = meta["primary_metric"]
    primary_result = run_metric_readout(experiment_id, primary_metric)

    secondary_results = []
    secondary_metrics = [m.strip() for m in (meta.get("secondary_metrics") or "").split(",") if m.strip()]
    for m in secondary_metrics:
        try:
            secondary_results.append(run_metric_readout(experiment_id, m))
        except Exception as exc:  # pragma: no cover - defensive, never fabricate
            logger.warning("Could not compute secondary metric '%s' for %s: %s", m, experiment_id, exc)

    guardrail_metrics = [g.strip() for g in (meta.get("guardrail_metrics") or "").split(",") if g.strip()]
    guardrail_results = guardrails_module.evaluate_all_guardrails(experiment_id, guardrail_metrics)

    logger.info("Full readout complete for %s (primary metric: %s)", experiment_id, primary_metric)

    return ExperimentReadout(
        experiment_id=experiment_id,
        meta=meta,
        control_n=control_n,
        treatment_n=treatment_n,
        srm=srm,
        primary_result=primary_result,
        secondary_results=secondary_results,
        guardrail_results=guardrail_results,
    )

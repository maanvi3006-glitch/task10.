"""
validation.py
---------------
Data-quality validation layer. Every metric surfaced on the dashboard must
be traceable to (a) a source table, (b) the SQL query used to compute it,
and (c) a set of validation checks (missing values, duplicates, outliers,
consistency). This module implements those checks against the live
SQLite database — it never assumes the data is clean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import database
from utils import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationReport:
    table: str
    row_count: int
    missing_value_counts: dict = field(default_factory=dict)
    duplicate_rows: int = 0
    duplicate_primary_keys: int = 0
    outlier_counts: dict = field(default_factory=dict)
    consistency_issues: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.duplicate_primary_keys == 0
            and not self.consistency_issues
        )


# Metric -> (source table, SQL query, formula, primary key column(s))
METRIC_METADATA = {
    "application_conversion": {
        "source_table": "Conversions",
        "sql_query": (
            "SELECT variant, AVG(converted) AS conversion_rate, COUNT(*) AS n "
            "FROM Conversions WHERE experiment_id = :exp_id GROUP BY variant"
        ),
        "formula": "conversion_rate = SUM(converted) / COUNT(user_id), computed separately per variant",
        "primary_key": ["experiment_id", "user_id"],
    },
    "revenue_per_user": {
        "source_table": "Revenue",
        "sql_query": (
            "SELECT variant, AVG(revenue) AS revenue_per_user, COUNT(*) AS n "
            "FROM Revenue WHERE experiment_id = :exp_id GROUP BY variant"
        ),
        "formula": "revenue_per_user = SUM(revenue) / COUNT(user_id) per variant (0 for non-converters)",
        "primary_key": ["experiment_id", "user_id"],
    },
    "retention_d7": {
        "source_table": "Retention",
        "sql_query": (
            "SELECT variant, AVG(retained_d7) AS retention_rate FROM Retention "
            "WHERE experiment_id = :exp_id GROUP BY variant"
        ),
        "formula": "retention_rate = SUM(retained_d7) / COUNT(user_id) per variant",
        "primary_key": ["experiment_id", "user_id"],
    },
    "crash_rate": {
        "source_table": "ExperimentEvents",
        "sql_query": (
            "SELECT variant, COUNT(DISTINCT user_id) * 1.0 / (SELECT COUNT(*) FROM "
            "ExperimentAssignments WHERE experiment_id = :exp_id AND variant = ea.variant) AS crash_rate "
            "FROM ExperimentEvents ea WHERE experiment_id = :exp_id AND event_type = 'crash_rate' "
            "GROUP BY variant"
        ),
        "formula": "crash_rate = users_with_crash_event / users_assigned, per variant",
        "primary_key": ["experiment_id", "user_id", "event_type"],
    },
    "error_rate": {
        "source_table": "ExperimentEvents",
        "sql_query": (
            "SELECT variant, COUNT(DISTINCT user_id) * 1.0 / (SELECT COUNT(*) FROM "
            "ExperimentAssignments WHERE experiment_id = :exp_id AND variant = ea.variant) AS error_rate "
            "FROM ExperimentEvents ea WHERE experiment_id = :exp_id AND event_type = 'error_rate' "
            "GROUP BY variant"
        ),
        "formula": "error_rate = users_with_error_event / users_assigned, per variant",
        "primary_key": ["experiment_id", "user_id", "event_type"],
    },
}


def validate_table(table: str, primary_key_cols: list[str] | None = None,
                    numeric_cols: list[str] | None = None) -> ValidationReport:
    """Run missing-value, duplicate and outlier checks against a live
    table in the SQLite database."""
    with database.get_connection() as conn:
        df = pd.read_sql(f"SELECT * FROM {table}", conn)

    report = ValidationReport(table=table, row_count=len(df))

    # Missing values
    for col in df.columns:
        n_missing = int(df[col].isna().sum())
        if n_missing:
            report.missing_value_counts[col] = n_missing

    # Full-row duplicates
    report.duplicate_rows = int(df.duplicated().sum())

    # Primary-key duplicates
    if primary_key_cols:
        missing_pk_cols = [c for c in primary_key_cols if c not in df.columns]
        if missing_pk_cols:
            report.consistency_issues.append(
                f"Declared primary key columns not found in table: {missing_pk_cols}"
            )
        else:
            report.duplicate_primary_keys = int(df.duplicated(subset=primary_key_cols).sum())
            if report.duplicate_primary_keys:
                report.consistency_issues.append(
                    f"{report.duplicate_primary_keys} duplicate primary-key rows found on {primary_key_cols}"
                )

    # Outlier detection (IQR method) on numeric columns
    numeric_cols = numeric_cols or df.select_dtypes(include=[np.number]).columns.tolist()
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 3 * iqr, q3 + 3 * iqr
        n_outliers = int(((series < lower) | (series > upper)).sum())
        if n_outliers:
            report.outlier_counts[col] = n_outliers

    logger.info("Validated table %s: %d rows, %d missing-value cols, %d dup PK rows, %d outlier cols",
                table, report.row_count, len(report.missing_value_counts),
                report.duplicate_primary_keys, len(report.outlier_counts))

    return report


def validate_experiment_consistency(experiment_id: str) -> list[str]:
    """Cross-table consistency checks specific to one experiment: every
    assigned user should appear at most once, and every event's user must
    have a corresponding assignment (no orphan events)."""
    issues: list[str] = []
    with database.get_connection() as conn:
        assignments = pd.read_sql(
            "SELECT user_id, variant FROM ExperimentAssignments WHERE experiment_id = ?",
            conn, params=(experiment_id,),
        )
        events = pd.read_sql(
            "SELECT DISTINCT user_id FROM ExperimentEvents WHERE experiment_id = ?",
            conn, params=(experiment_id,),
        )

    dup_users = assignments["user_id"].duplicated().sum()
    if dup_users:
        issues.append(f"{dup_users} users assigned to more than one variant in {experiment_id}.")

    orphan_events = set(events["user_id"]) - set(assignments["user_id"])
    if orphan_events:
        issues.append(
            f"{len(orphan_events)} users have events logged for {experiment_id} without an assignment record."
        )

    if not issues:
        logger.info("Experiment %s passed cross-table consistency checks.", experiment_id)
    else:
        logger.warning("Experiment %s failed consistency checks: %s", experiment_id, issues)

    return issues


def run_all_validations() -> dict[str, ValidationReport]:
    tables = {
        "Users": ["user_id"],
        "Companies": ["company_id"],
        "Jobs": ["job_id"],
        "Sessions": ["session_id"],
        "Applications": ["application_id"],
        "Experiments": ["experiment_id"],
        "ExperimentAssignments": ["assignment_id"],
        "ExperimentEvents": ["event_id"],
    }
    return {t: validate_table(t, pk) for t, pk in tables.items()}

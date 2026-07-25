"""
database.py
------------
All SQLite access for the PlaceMux Growth Experimentation Analytics
Platform lives here: schema creation, CSV import, derived-table
materialization (Conversions, Revenue, Retention, Errors) and a small
set of typed query helpers used by the statistics / guardrail / SRM
engines and the Streamlit dashboard.

Design notes
------------
* SQLite is used (file-based, zero-ops) as specified in the brief.
* Raw CSVs are loaded verbatim into normalized tables that mirror the
  production event log shape (ExperimentEvents, ExperimentAssignments).
* Derived tables (Conversions, Revenue, Retention, Errors) are rebuilt
  from the raw event log every time `build_database()` runs, so they are
  always a deterministic function of the raw data — never hand-edited.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

import config
from utils import get_logger

logger = get_logger(__name__)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Context-managed SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_schema() -> None:
    """Execute create_tables.sql to (re)build an empty, normalized schema."""
    schema_sql = (config.SQL_DIR / "create_tables.sql").read_text()
    with get_connection() as conn:
        conn.executescript(schema_sql)
    logger.info("Schema created from %s", config.SQL_DIR / "create_tables.sql")


def _load_csv(conn: sqlite3.Connection, csv_name: str, table: str, if_exists: str = "append") -> int:
    path = config.DATA_DIR / csv_name
    if not path.exists():
        raise FileNotFoundError(
            f"Expected input CSV missing: {path}. Run scripts/generate_data.py first."
        )
    df = pd.read_csv(path)
    df.to_sql(table, conn, if_exists=if_exists, index=False)
    logger.info("Loaded %d rows from %s into %s", len(df), csv_name, table)
    return len(df)


def load_csvs() -> None:
    """Load all raw CSVs from data/ into their corresponding tables."""
    with get_connection() as conn:
        _load_csv(conn, "users.csv", "Users")
        _load_csv(conn, "companies.csv", "Companies")
        _load_csv(conn, "jobs.csv", "Jobs")
        _load_csv(conn, "sessions.csv", "Sessions")
        _load_csv(conn, "applications.csv", "Applications")
        _load_csv(conn, "experiments.csv", "Experiments")
        _load_csv(conn, "experiment_assignments.csv", "ExperimentAssignments")
        _load_csv(conn, "experiment_events.csv", "ExperimentEvents")


def materialize_derived_tables() -> None:
    """Rebuild Conversions / Revenue / Retention / Errors purely from
    ExperimentAssignments + ExperimentEvents (the raw event log). This
    guarantees every downstream statistic traces back to raw data, per the
    task's validation requirement ("every number must trace back to raw
    data")."""
    with get_connection() as conn:
        assignments = pd.read_sql(
            "SELECT experiment_id, user_id, variant FROM ExperimentAssignments", conn
        )
        events = pd.read_sql(
            "SELECT experiment_id, user_id, variant, event_type, event_value FROM ExperimentEvents",
            conn,
        )

        # Conversions: any 'conversion' event for that user/experiment.
        conv_users = (
            events[events.event_type == "conversion"][["experiment_id", "user_id"]]
            .drop_duplicates()
        )
        conv_users["converted"] = 1
        conversions = assignments.merge(conv_users, on=["experiment_id", "user_id"], how="left")
        conversions["converted"] = conversions["converted"].fillna(0).astype(int)
        conversions[["experiment_id", "variant", "user_id", "converted"]].to_sql(
            "Conversions", conn, if_exists="replace", index=False
        )

        # Revenue: sum of 'revenue' event_value per user/experiment (0 if none).
        rev = (
            events[events.event_type == "revenue"]
            .groupby(["experiment_id", "user_id"])["event_value"].sum()
            .reset_index()
            .rename(columns={"event_value": "revenue"})
        )
        revenue = assignments.merge(rev, on=["experiment_id", "user_id"], how="left")
        revenue["revenue"] = revenue["revenue"].fillna(0.0)
        revenue[["experiment_id", "variant", "user_id", "revenue"]].to_sql(
            "Revenue", conn, if_exists="replace", index=False
        )

        # Retention proxy: users with a conversion event are treated as
        # "retained" for the D7 guardrail illustration (explicitly documented
        # as a proxy — see SCHEMA.md).
        retention = conversions.rename(columns={"converted": "retained_d7"})
        retention[["experiment_id", "variant", "user_id", "retained_d7"]].to_sql(
            "Retention", conn, if_exists="replace", index=False
        )

        # Errors: count of 'error_rate' flagged events per user/experiment.
        err = (
            events[events.event_type == "error_rate"]
            .groupby(["experiment_id", "user_id"]).size()
            .reset_index(name="error_count")
        )
        errors = assignments.merge(err, on=["experiment_id", "user_id"], how="left")
        errors["error_count"] = errors["error_count"].fillna(0).astype(int)
        errors[["experiment_id", "variant", "user_id", "error_count"]].to_sql(
            "Errors", conn, if_exists="replace", index=False
        )

    logger.info("Derived tables (Conversions, Revenue, Retention, Errors) rebuilt from raw events.")


def build_database(force: bool = True) -> None:
    """Full pipeline: schema -> load CSVs -> materialize derived tables."""
    if force and Path(config.DB_PATH).exists():
        Path(config.DB_PATH).unlink()
        logger.info("Removed existing database at %s", config.DB_PATH)
    run_schema()
    load_csvs()
    materialize_derived_tables()
    logger.info("Database build complete: %s", config.DB_PATH)


def list_experiments() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM Experiments ORDER BY start_date", conn)


def get_experiment(experiment_id: str) -> pd.Series:
    with get_connection() as conn:
        df = pd.read_sql(
            "SELECT * FROM Experiments WHERE experiment_id = ?", conn, params=(experiment_id,)
        )
    if df.empty:
        raise ValueError(f"Unknown experiment_id: {experiment_id}")
    return df.iloc[0]


def get_assignment_counts(experiment_id: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql(
            """
            SELECT variant, COUNT(*) AS n
            FROM ExperimentAssignments
            WHERE experiment_id = ?
            GROUP BY variant
            """,
            conn, params=(experiment_id,),
        )


def get_conversions(experiment_id: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql(
            "SELECT variant, user_id, converted FROM Conversions WHERE experiment_id = ?",
            conn, params=(experiment_id,),
        )


def get_revenue(experiment_id: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql(
            "SELECT variant, user_id, revenue FROM Revenue WHERE experiment_id = ?",
            conn, params=(experiment_id,),
        )


def get_guardrail_raw(experiment_id: str, event_type: str) -> pd.DataFrame:
    """Per-user 0/1 indicator of whether a guardrail event fired, joined
    against the full assignment population (so users with zero events are
    correctly counted as 0, not dropped)."""
    with get_connection() as conn:
        assignments = pd.read_sql(
            "SELECT experiment_id, user_id, variant FROM ExperimentAssignments WHERE experiment_id = ?",
            conn, params=(experiment_id,),
        )
        events = pd.read_sql(
            """
            SELECT DISTINCT experiment_id, user_id
            FROM ExperimentEvents
            WHERE experiment_id = ? AND event_type = ?
            """,
            conn, params=(experiment_id, event_type),
        )
    events["flag"] = 1
    merged = assignments.merge(events, on=["experiment_id", "user_id"], how="left")
    merged["flag"] = merged["flag"].fillna(0).astype(int)
    return merged[["variant", "user_id", "flag"]]


def save_guardrail_result(experiment_id: str, metric_name: str, control_rate: float,
                           treatment_rate: float, relative_change: float, is_regression: bool,
                           p_value: float | None, evaluated_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO Guardrails (experiment_id, metric_name, control_rate, treatment_rate,
                                     relative_change, is_regression, p_value, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (experiment_id, metric_name, control_rate, treatment_rate, relative_change,
             int(is_regression), p_value, evaluated_at),
        )


def save_experiment_log(experiment_id: str, experiment_name: str, owner: str, objective: str,
                         hypothesis: str, primary_metric_result: str, decision: str,
                         reasoning: str, lessons_learned: str, next_experiment: str,
                         logged_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ExperimentLogs (experiment_id, experiment_name, owner, objective, hypothesis,
                                         primary_metric_result, decision, reasoning, lessons_learned,
                                         next_experiment, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (experiment_id, experiment_name, owner, objective, hypothesis, primary_metric_result,
             decision, reasoning, lessons_learned, next_experiment, logged_at),
        )


def get_experiment_logs(experiment_id: str | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        if experiment_id:
            return pd.read_sql(
                "SELECT * FROM ExperimentLogs WHERE experiment_id = ? ORDER BY logged_at DESC",
                conn, params=(experiment_id,),
            )
        return pd.read_sql("SELECT * FROM ExperimentLogs ORDER BY logged_at DESC", conn)


def get_guardrail_history(experiment_id: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql(
            "SELECT * FROM Guardrails WHERE experiment_id = ? ORDER BY evaluated_at DESC",
            conn, params=(experiment_id,),
        )


if __name__ == "__main__":
    build_database(force=True)

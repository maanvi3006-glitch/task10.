"""
config.py
---------
Central configuration for the PlaceMux Growth Experimentation Analytics
Platform. All paths, statistical thresholds and constants used across the
project are defined here so that every module (database, engines,
dashboard, reports) shares a single source of truth.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent

DATA_DIR: Path = BASE_DIR / "data"
DATABASE_DIR: Path = BASE_DIR / "database"
SQL_DIR: Path = BASE_DIR / "sql"
REPORTS_DIR: Path = BASE_DIR / "reports"
SCREENSHOTS_DIR: Path = BASE_DIR / "screenshots"
LOG_DIR: Path = BASE_DIR / "logs"

for _dir in (DATA_DIR, DATABASE_DIR, SQL_DIR, REPORTS_DIR, SCREENSHOTS_DIR, LOG_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

DB_PATH: str = str(DATABASE_DIR / "placemux.db")

# --------------------------------------------------------------------------
# Statistical configuration
# --------------------------------------------------------------------------
# Significance levels supported by the confidence-interval engine.
CONFIDENCE_LEVELS = {
    "95%": 0.05,
    "99%": 0.01,
}

DEFAULT_ALPHA: float = 0.05          # two-sided significance threshold
DEFAULT_POWER_TARGET: float = 0.80   # standard target statistical power
MIN_SAMPLE_PER_ARM: int = 200        # below this, results are flagged low-power

# SRM (Sample Ratio Mismatch) chi-square p-value threshold. Anything below
# this is flagged as a sample-ratio mismatch that invalidates the readout.
SRM_P_VALUE_THRESHOLD: float = 0.001

# Guardrail regression tolerance (relative). A guardrail that regresses by
# more than this percentage (in the "bad" direction) is flagged.
GUARDRAIL_REGRESSION_TOLERANCE: float = 0.02  # 2%

# --------------------------------------------------------------------------
# Metric definitions
# --------------------------------------------------------------------------
# Metrics that are proportions (conversion-style) use a two-proportion
# z-test / chi-square test. Metrics that are continuous (revenue, duration)
# use a t-test / Mann-Whitney U test depending on distribution shape.
PROPORTION_METRICS = {
    "application_conversion",
    "activation_rate",
    "retention_d7",
    "crash_rate",
    "error_rate",
    "cancellation_rate",
    "refund_rate",
    "bounce_rate",
    "application_success_rate",
}

CONTINUOUS_METRICS = {
    "revenue_per_user",
    "session_duration",
    "latency_ms",
}

# Guardrail metrics and the direction in which an increase is "bad".
# True  -> an increase in this metric is a regression (bad).
# False -> a decrease in this metric is a regression (bad).
GUARDRAIL_METRICS = {
    "crash_rate": True,
    "latency_ms": True,
    "bounce_rate": True,
    "error_rate": True,
    "cancellation_rate": True,
    "refund_rate": True,
    "application_success_rate": False,
    "retention_d7": False,
    "revenue_per_user": False,
}

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_FILE: str = str(LOG_DIR / "placemux_growth.log")
LOG_LEVEL: str = os.environ.get("PLACEMUX_LOG_LEVEL", "INFO")

RANDOM_SEED: int = 42

"""
utils.py
--------
Small, reusable helper functions shared across the platform: logging setup,
safe-division, rounding helpers and dataframe validation shortcuts.

Keeping these in one place avoids duplicate logic in the statistics,
guardrail, SRM and recommendation engines.
"""

from __future__ import annotations

import logging
from typing import Optional

import config


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger configured to write to the shared
    PlaceMux log file and to stdout.

    Args:
        name: Usually ``__name__`` of the calling module.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured (avoid duplicate handlers on re-import).
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide two numbers, returning ``default`` instead of raising on a
    zero denominator. Used throughout the statistics engine so a single
    empty experiment arm never crashes the whole readout.
    """
    if denominator in (0, 0.0, None):
        return default
    return numerator / denominator


def round_or_none(value: Optional[float], digits: int = 4) -> Optional[float]:
    """Round a numeric value, passing ``None`` through untouched. Used when
    serialising statistics results to dicts / JSON where some fields are
    legitimately undefined (e.g. MDE when power cannot be computed)."""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def pct(value: float, digits: int = 2) -> str:
    """Format a proportion (0-1) as a human-readable percentage string."""
    return f"{value * 100:.{digits}f}%"

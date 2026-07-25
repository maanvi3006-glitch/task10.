"""
scripts/generate_data.py
-------------------------
Generates a production-like PlaceMux marketplace dataset (job-search /
hiring marketplace, similar to a Naukri/LinkedIn-style product) with three
realistic, pre-registered A/B experiments.

IMPORTANT — what this script does and does NOT do
====================================================
This script does NOT fabricate experiment *conclusions*. It generates
underlying user-level event data with embedded (but hidden-from-the-
analysis-code) true effect sizes, in the same way a real randomized
controlled trial produces real, noisy data. The actual conversion rates,
p-values, confidence intervals, SRM flags, guardrail regressions and
ship/no-ship recommendations are computed *afterwards* by
`statistics.py`, `srm_checker.py`, `guardrails.py` and
`recommendation_engine.py` purely from this generated data — exactly as
they would be computed from a real production database export. No
statistical result is hand-written anywhere in the codebase.

Three experiments are simulated to give an honest, mixed portfolio:

1. exp_1001 "Resume Upload Simplification"
   A genuine, meaningful improvement to application conversion, with no
   guardrail regression -> expected to read out as a clear SHIP.

2. exp_1002 "Aggressive Push Notification Frequency"
   Improves a secondary engagement metric slightly but visibly regresses
   guardrail metrics (uninstall/cancellation, error rate) -> expected to
   read out as a NO-SHIP / negative result.

3. exp_1003 "New Job Recommendation Ranking Model"
   A small, true effect that is too small to reliably detect at the
   current sample size -> expected to read out as INCONCLUSIVE / CONTINUE.

4. exp_1004 "Onboarding Checklist Redesign"
   Deliberately assigned with an imbalanced randomization unit (to
   demonstrate a real Sample Ratio Mismatch) -> expected to read out as
   SRM FLAGGED / INVALID READOUT.

Run:
    python scripts/generate_data.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

rng = np.random.default_rng(config.RANDOM_SEED)

N_USERS = 42_000
N_COMPANIES = 600
N_JOBS = 5_000
COUNTRIES = ["IN", "US", "UK", "AE", "SG", "DE"]
DEVICES = ["android", "ios", "web"]
INDUSTRIES = [
    "Technology", "Finance", "Healthcare", "Retail", "Manufacturing",
    "Education", "Logistics", "Hospitality",
]
JOB_CATEGORIES = [
    "Software Engineering", "Sales", "Marketing", "Data & Analytics",
    "Customer Support", "Operations", "Design", "Finance & Accounting",
]

START_DATE = datetime(2026, 3, 1)


def _random_dates(n: int, start: datetime, days: int) -> list[datetime]:
    offsets = rng.integers(0, days, size=n)
    return [start + timedelta(days=int(o), seconds=int(rng.integers(0, 86400))) for o in offsets]


def generate_users() -> pd.DataFrame:
    signup_dates = _random_dates(N_USERS, START_DATE - timedelta(days=365), 365)
    df = pd.DataFrame({
        "user_id": np.arange(1, N_USERS + 1),
        "signup_date": [d.date().isoformat() for d in signup_dates],
        "country": rng.choice(COUNTRIES, N_USERS, p=[0.45, 0.2, 0.12, 0.08, 0.08, 0.07]),
        "device": rng.choice(DEVICES, N_USERS, p=[0.55, 0.30, 0.15]),
        "plan": rng.choice(["free", "premium"], N_USERS, p=[0.86, 0.14]),
    })
    return df


def generate_companies() -> pd.DataFrame:
    df = pd.DataFrame({
        "company_id": np.arange(1, N_COMPANIES + 1),
        "company_name": [f"Company_{i:04d}" for i in range(1, N_COMPANIES + 1)],
        "industry": rng.choice(INDUSTRIES, N_COMPANIES),
        "company_size": rng.choice(
            ["1-50", "51-200", "201-1000", "1000+"], N_COMPANIES,
            p=[0.4, 0.3, 0.2, 0.1],
        ),
    })
    return df


def generate_jobs(companies: pd.DataFrame) -> pd.DataFrame:
    posted = _random_dates(N_JOBS, START_DATE - timedelta(days=200), 260)
    df = pd.DataFrame({
        "job_id": np.arange(1, N_JOBS + 1),
        "company_id": rng.choice(companies["company_id"], N_JOBS),
        "title": rng.choice(JOB_CATEGORIES, N_JOBS),
        "category": rng.choice(JOB_CATEGORIES, N_JOBS),
        "posted_date": [d.date().isoformat() for d in posted],
        "is_remote": rng.choice([0, 1], N_JOBS, p=[0.7, 0.3]),
    })
    return df


def generate_sessions(users: pd.DataFrame) -> pd.DataFrame:
    # Each user has a Poisson number of sessions over the observation window.
    n_sessions_per_user = rng.poisson(lam=6, size=len(users))
    n_sessions_per_user = np.clip(n_sessions_per_user, 0, 60)
    rows = []
    sid = 1
    session_dates = _random_dates(int(n_sessions_per_user.sum()), START_DATE - timedelta(days=60), 150)
    idx = 0
    for uid, n in zip(users["user_id"], n_sessions_per_user):
        for _ in range(n):
            duration = max(5, rng.normal(240, 120))
            rows.append((sid, uid, session_dates[idx].isoformat(sep=" "), round(float(duration), 1),
                         rng.choice(DEVICES)))
            sid += 1
            idx += 1
    df = pd.DataFrame(rows, columns=["session_id", "user_id", "session_ts", "duration_sec", "device"])
    return df


def generate_applications(users: pd.DataFrame, jobs: pd.DataFrame) -> pd.DataFrame:
    n_apps_per_user = rng.poisson(lam=1.4, size=len(users))
    n_apps_per_user = np.clip(n_apps_per_user, 0, 20)
    total = int(n_apps_per_user.sum())
    app_dates = _random_dates(total, START_DATE - timedelta(days=45), 120)
    rows = []
    aid = 1
    idx = 0
    statuses = ["submitted", "viewed", "shortlisted", "rejected", "hired"]
    status_p = [0.45, 0.25, 0.15, 0.12, 0.03]
    for uid, n in zip(users["user_id"], n_apps_per_user):
        for _ in range(n):
            job_id = int(rng.choice(jobs["job_id"]))
            status = rng.choice(statuses, p=status_p)
            rows.append((aid, uid, job_id, app_dates[idx].date().isoformat(), status))
            aid += 1
            idx += 1
    df = pd.DataFrame(rows, columns=["application_id", "user_id", "job_id", "applied_date", "status"])
    return df


# --------------------------------------------------------------------------
# Experiment simulation
# --------------------------------------------------------------------------

def _assign_variants(user_ids: np.ndarray, split: float = 0.5) -> np.ndarray:
    draws = rng.random(len(user_ids))
    return np.where(draws < split, "control", "treatment")


def _simulate_experiment(
    experiment_id: str,
    user_ids: np.ndarray,
    assign_start: datetime,
    duration_days: int,
    control_conv: float,
    treatment_conv: float,
    control_guardrail_rates: dict,
    treatment_guardrail_rates: dict,
    control_revenue_mean: float,
    treatment_revenue_mean: float,
    split: float = 0.5,
    srm_bias: float = 0.0,
):
    """Simulate one experiment: assignments + downstream events.

    ``srm_bias`` shifts the effective randomization split away from the
    nominal 50/50 (used to construct exp_1004's genuine SRM).
    """
    n = len(user_ids)
    effective_split = split + srm_bias
    draws = rng.random(n)
    variants = np.where(draws < effective_split, "control", "treatment")

    assign_dates = _random_dates(n, assign_start, max(duration_days - 3, 1))

    assignments = pd.DataFrame({
        "assignment_id": [f"{experiment_id}_{i}" for i in range(1, n + 1)],
        "experiment_id": experiment_id,
        "user_id": user_ids,
        "variant": variants,
        "assigned_ts": [d.isoformat(sep=" ") for d in assign_dates],
    })

    events = []
    eid = 1
    for uid, variant, adate in zip(user_ids, variants, assign_dates):
        conv_p = control_conv if variant == "control" else treatment_conv
        converted = rng.random() < conv_p
        event_date = adate + timedelta(days=int(rng.integers(0, max(duration_days - 1, 1))))

        if converted:
            events.append((f"{experiment_id}_e{eid}", experiment_id, uid, variant, "conversion", 1,
                            event_date.isoformat(sep=" ")))
            eid += 1
            rev_mean = control_revenue_mean if variant == "control" else treatment_revenue_mean
            revenue = max(0.0, rng.normal(rev_mean, rev_mean * 0.4))
            events.append((f"{experiment_id}_e{eid}", experiment_id, uid, variant, "revenue", round(float(revenue), 2),
                            event_date.isoformat(sep=" ")))
            eid += 1

        g_rates = control_guardrail_rates if variant == "control" else treatment_guardrail_rates
        for g_metric, g_p in g_rates.items():
            if rng.random() < g_p:
                events.append((f"{experiment_id}_e{eid}", experiment_id, uid, variant, g_metric, 1,
                                (event_date + timedelta(hours=int(rng.integers(1, 48)))).isoformat(sep=" ")))
                eid += 1

    events_df = pd.DataFrame(
        events, columns=["event_id", "experiment_id", "user_id", "variant", "event_type",
                          "event_value", "event_ts"],
    )
    return assignments, events_df


def generate_experiments_and_events(users: pd.DataFrame):
    all_uids = users["user_id"].to_numpy()

    experiments_meta = pd.DataFrame([
        {
            "experiment_id": "exp_1001",
            "experiment_name": "Resume Upload Simplification",
            "business_goal": "Increase completed job applications by reducing resume-upload friction",
            "primary_metric": "application_conversion",
            "secondary_metrics": "session_duration,revenue_per_user",
            "guardrail_metrics": "crash_rate,error_rate,application_success_rate",
            "hypothesis": "A one-click resume autofill increases the share of sessions that end in a submitted application without harming quality of applications",
            "owner": "growth-pm@placemux.com",
            "start_date": "2026-04-01",
            "end_date": "2026-04-21",
            "decision_date": "2026-04-24",
            "status": "concluded",
        },
        {
            "experiment_id": "exp_1002",
            "experiment_name": "Aggressive Push Notification Frequency",
            "business_goal": "Increase weekly active usage via higher-frequency push reminders",
            "primary_metric": "application_conversion",
            "secondary_metrics": "session_duration",
            "guardrail_metrics": "cancellation_rate,error_rate,refund_rate",
            "hypothesis": "Sending 3x more push notifications per week increases re-engagement and application conversion",
            "owner": "growth-pm@placemux.com",
            "start_date": "2026-04-05",
            "end_date": "2026-04-25",
            "decision_date": "2026-04-28",
            "status": "concluded",
        },
        {
            "experiment_id": "exp_1003",
            "experiment_name": "New Job Recommendation Ranking Model",
            "business_goal": "Improve relevance of recommended jobs to increase application conversion",
            "primary_metric": "application_conversion",
            "secondary_metrics": "revenue_per_user",
            "guardrail_metrics": "error_rate,bounce_rate",
            "hypothesis": "A learning-to-rank model for job recommendations increases application conversion vs. the recency-based baseline",
            "owner": "search-ranking@placemux.com",
            "start_date": "2026-04-10",
            "end_date": "2026-04-30",
            "decision_date": "2026-05-03",
            "status": "concluded",
        },
        {
            "experiment_id": "exp_1004",
            "experiment_name": "Onboarding Checklist Redesign",
            "business_goal": "Increase activation (profile completion) for new signups",
            "primary_metric": "application_conversion",
            "secondary_metrics": "session_duration",
            "guardrail_metrics": "error_rate,bounce_rate",
            "hypothesis": "A shorter, gamified onboarding checklist increases new-user activation",
            "owner": "activation-pm@placemux.com",
            "start_date": "2026-04-12",
            "end_date": "2026-05-02",
            "decision_date": "2026-05-05",
            "status": "concluded",
        },
    ])

    assignments_frames = []
    events_frames = []

    # --- exp_1001: true, meaningful, clean win --------------------------
    uids_1 = rng.choice(all_uids, size=9000, replace=False)
    a1, e1 = _simulate_experiment(
        "exp_1001", uids_1, datetime(2026, 4, 1), 21,
        control_conv=0.24, treatment_conv=0.26,   # ~8.3% relative lift
        control_guardrail_rates={"crash_rate": 0.010, "error_rate": 0.020,
                                  "application_success_rate_fail": 0.05},
        treatment_guardrail_rates={"crash_rate": 0.010, "error_rate": 0.019,
                                    "application_success_rate_fail": 0.048},
        control_revenue_mean=18.0, treatment_revenue_mean=18.6,
    )
    assignments_frames.append(a1); events_frames.append(e1)

    # --- exp_1002: engagement up, guardrails regress ---------------------
    uids_2 = rng.choice(all_uids, size=8500, replace=False)
    a2, e2 = _simulate_experiment(
        "exp_1002", uids_2, datetime(2026, 4, 5), 20,
        control_conv=0.235, treatment_conv=0.239,   # tiny, noisy lift
        control_guardrail_rates={"cancellation_rate": 0.018, "error_rate": 0.021,
                                  "refund_rate": 0.010},
        treatment_guardrail_rates={"cancellation_rate": 0.031, "error_rate": 0.034,
                                    "refund_rate": 0.017},
        control_revenue_mean=18.2, treatment_revenue_mean=18.1,
    )
    assignments_frames.append(a2); events_frames.append(e2)

    # --- exp_1003: real but small effect, underpowered --------------------
    uids_3 = rng.choice(all_uids, size=4000, replace=False)
    a3, e3 = _simulate_experiment(
        "exp_1003", uids_3, datetime(2026, 4, 10), 20,
        control_conv=0.240, treatment_conv=0.246,   # true 2.5% relative lift, small N
        control_guardrail_rates={"error_rate": 0.020, "bounce_rate": 0.30},
        treatment_guardrail_rates={"error_rate": 0.020, "bounce_rate": 0.295},
        control_revenue_mean=18.0, treatment_revenue_mean=18.1,
    )
    assignments_frames.append(a3); events_frames.append(e3)

    # --- exp_1004: SRM injected via biased assignment ---------------------
    uids_4 = rng.choice(all_uids, size=7000, replace=False)
    a4, e4 = _simulate_experiment(
        "exp_1004", uids_4, datetime(2026, 4, 12), 20,
        control_conv=0.242, treatment_conv=0.250,
        control_guardrail_rates={"error_rate": 0.020, "bounce_rate": 0.30},
        treatment_guardrail_rates={"error_rate": 0.021, "bounce_rate": 0.29},
        control_revenue_mean=18.0, treatment_revenue_mean=18.3,
        srm_bias=0.09,  # pushes ~59/41 instead of 50/50 -> real SRM
    )
    assignments_frames.append(a4); events_frames.append(e4)

    assignments = pd.concat(assignments_frames, ignore_index=True)
    events = pd.concat(events_frames, ignore_index=True)
    return experiments_meta, assignments, events


def main() -> None:
    print("Generating users...")
    users = generate_users()
    print("Generating companies...")
    companies = generate_companies()
    print("Generating jobs...")
    jobs = generate_jobs(companies)
    print("Generating sessions...")
    sessions = generate_sessions(users)
    print("Generating applications...")
    applications = generate_applications(users, jobs)
    print("Generating experiments, assignments and events...")
    experiments, assignments, events = generate_experiments_and_events(users)

    out = config.DATA_DIR
    users.to_csv(out / "users.csv", index=False)
    companies.to_csv(out / "companies.csv", index=False)
    jobs.to_csv(out / "jobs.csv", index=False)
    sessions.to_csv(out / "sessions.csv", index=False)
    applications.to_csv(out / "applications.csv", index=False)
    experiments.to_csv(out / "experiments.csv", index=False)
    assignments.to_csv(out / "experiment_assignments.csv", index=False)
    events.to_csv(out / "experiment_events.csv", index=False)

    print("\nRow counts:")
    for name, df in [
        ("users", users), ("companies", companies), ("jobs", jobs),
        ("sessions", sessions), ("applications", applications),
        ("experiments", experiments), ("experiment_assignments", assignments),
        ("experiment_events", events),
    ]:
        print(f"  {name:28s} {len(df):>8,d}")


if __name__ == "__main__":
    main()

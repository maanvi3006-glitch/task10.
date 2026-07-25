# PlaceMux Growth Experimentation Analytics Platform

Task 10 (Phase 3) — Growth Integration & Experiment Readout.

A production-style A/B testing readout platform: rigorous statistics
(z-test / t-test / chi-square / Fisher's exact / Mann-Whitney), 95%/99%
confidence intervals, Sample Ratio Mismatch (SRM) detection, guardrail
regression monitoring, an evidence-gated ship/no-ship recommendation
engine, a Streamlit dashboard, and PDF reporting — all computed live from
a normalized SQLite database, never fabricated.

## What "good" means here

> Decisions get made on evidence, including the unpopular decision to kill
> a favourite feature.

The bundled dataset intentionally contains a mixed, honest portfolio:
one clear win (**Ship**), one experiment that improves the primary metric
but regresses guardrails (**No Ship**), one true-but-underpowered effect,
and one experiment with a genuine Sample Ratio Mismatch (**Rollback** —
readout untrustworthy until the pipeline is fixed). Nothing here is
cherry-picked to always say "ship."

## Installation

```bash
cd placemux_growth
pip install -r requirements.txt
```

Requires Python 3.10+.

## Quickstart

```bash
# 1. Generate the production-like marketplace + experiment dataset (CSV files in data/)
python scripts/generate_data.py

# 2. Build the normalized SQLite database from those CSVs
python database.py

# 3. (Optional) populate the experiment learning log for all experiments
python experiment_logger.py

# 4. (Optional) generate the PDF deliverables
python scripts/generate_reports.py

# 5. Launch the dashboard
streamlit run app.py
```

## Database setup

`database.py` runs `sql/create_tables.sql` (DDL: PKs, FKs, CHECK
constraints, indexes) against a fresh SQLite file, loads every CSV in
`data/` into its matching table, then rebuilds the derived tables
(`Conversions`, `Revenue`, `Retention`, `Errors`) purely from the raw
`ExperimentAssignments` + `ExperimentEvents` log. Re-running
`python database.py` always produces a byte-for-byte-consistent database
from the same CSVs — see `SCHEMA.md` for full table documentation.

## CSV import

CSVs live in `data/` and are the platform's only external input:
`users.csv`, `companies.csv`, `jobs.csv`, `sessions.csv`,
`applications.csv`, `experiments.csv`, `experiment_assignments.csv`,
`experiment_events.csv`. `scripts/generate_data.py` produces a
production-like version of this data (real event-simulation with embedded
true effect sizes — see the module docstring for exactly what is and is
not fabricated). To point the platform at your own production export,
replace these CSVs with matching columns and re-run `python database.py`.

## Running the dashboard

```bash
streamlit run app.py
```

Pages: **Overview** (portfolio KPIs) · **Experiment Summary** (traffic
split, primary KPI, decision) · **Statistical Analysis** (CI, p-values,
power, distributions) · **Guardrails** (regression monitoring + history) ·
**SRM** (allocation checks) · **Recommendation** (full ship/no-ship
reasoning) · **Experiment Log** (history & learnings) · **Validation**
(source table / SQL / formula / data-quality checks per metric).

Global controls in the sidebar: experiment selector, dark mode toggle,
informational date-range filter. CSV/Markdown export buttons are on the
Overview, Experiment Log and Recommendation pages.

## Generating reports

```bash
python scripts/generate_reports.py
```

Writes two PDFs to `reports/`:
- `experiment_report.pdf` — full multi-experiment statistical readout
  (executive summary, design, CI, SRM, guardrails, recommendation, per
  experiment).
- `ship_decision.pdf` — condensed, leadership-facing ship/no-ship memo.

Both are generated entirely from live `ExperimentReadout` /
`Recommendation` objects — no numbers are hard-coded in the report code.

## Folder structure

```
placemux_growth/
├── app.py                     # Streamlit dashboard entry point
├── config.py                  # paths, alpha, thresholds, metric config
├── database.py                # schema, CSV load, derived tables, query helpers
├── experiment_engine.py       # orchestrates a full experiment readout
├── statistics.py              # z-test, t-test, chi-square, Fisher, Mann-Whitney, CI, power
├── guardrails.py              # guardrail regression evaluation
├── srm_checker.py             # Sample Ratio Mismatch detection
├── recommendation_engine.py   # evidence-gated ship/no-ship decision logic
├── experiment_logger.py       # experiment learning log persistence
├── validation.py              # data-quality checks + metric metadata
├── utils.py                   # logging, safe-divide, rounding helpers
├── requirements.txt
├── README.md
├── SCHEMA.md
├── database/placemux.db       # built by database.py
├── sql/
│   ├── create_tables.sql      # DDL: PKs, FKs, CHECK constraints, indexes
│   └── experiment_queries.sql # reference SQL for every metric
├── data/                      # input CSVs
├── notebooks/exploration.ipynb
├── reports/                   # generated PDF deliverables
├── dashboards/experiment_dashboard.py  # Plotly chart builders used by app.py
├── screenshots/               # dashboard screenshots (see below)
└── scripts/
    ├── generate_data.py       # builds the production-like dataset
    └── generate_reports.py    # builds the PDF deliverables
```

## SQL schema

See `SCHEMA.md` for the full table-by-table documentation, and
`sql/create_tables.sql` / `sql/experiment_queries.sql` for the DDL and the
reference query for every metric on the dashboard.

## Assumptions

- Data is **simulated but not fabricated-as-conclusions**: `generate_data.py`
  produces raw, noisy, per-user events with embedded true effect sizes,
  exactly like a real RCT; every statistic, CI, p-value, SRM flag,
  guardrail regression and ship/no-ship decision is then computed by the
  statistics/guardrail/SRM/recommendation engines from that raw data —
  never hand-written. This mirrors "sampled production data" since a real
  production export was not available for this exercise.
- `retention_d7` is currently a proxy for the conversion flag (documented
  in `SCHEMA.md`) because the simulated dataset does not model multi-week
  return visits. The SQL shape for a true recurrence-based retention
  metric is included as a template.
- Default randomization split is 50/50 control/treatment unless an
  experiment's assignment data indicates otherwise (which is exactly how
  `exp_1004`'s SRM is detected — from the data, not from a flag).
- Significance threshold: α = 0.05 (95%) as the primary gate, with 99% CI
  also reported. SRM threshold: p < 0.001 (industry standard). Guardrail
  regression requires both statistical significance AND harmful direction.
- Minimum practical relative lift to recommend "Ship" on a significant
  result: 1.0% (configurable in `recommendation_engine.py`) — guards
  against shipping statistically-real-but-business-irrelevant effects.

## Future improvements

- Wire `application_success_rate` into the guardrail event-type map (see
  `SCHEMA.md` "known modeling simplifications").
- Replace the retention proxy with a true D7-recurrence query once
  multi-visit session data is available.
- Add sequential/always-valid testing (e.g. mSPRT) to support safe peeking
  instead of a single fixed-horizon readout.
- Add a CUPED-style variance-reduction option to the statistics engine for
  higher-powered readouts at the same sample size.
- Persist per-day metric snapshots to a `MetricSnapshots` table to support
  richer trend charts than the current on-the-fly event aggregation.

## Coding standards

Modular architecture (one concern per file), PEP8-formatted, type hints
throughout, docstrings on every public function/class, defensive
exception handling (engines never crash the dashboard — they log and
degrade to "N/A" rather than fabricating a number), and a single shared
logger (`utils.get_logger`) writing to `logs/placemux_growth.log`.
"# task10." 

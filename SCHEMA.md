# SCHEMA.md — PlaceMux Growth Experimentation Database

Database engine: **SQLite** (`database/placemux.db`), built by `database.py`
from `sql/create_tables.sql` and the CSVs in `data/`.

## Entity groups

### 1. Core marketplace tables (context for experiments)

| Table | Grain | Key columns | Notes |
|---|---|---|---|
| `Users` | 1 row / user | `user_id` (PK) | signup_date, country, device, plan |
| `Companies` | 1 row / company | `company_id` (PK) | industry, company_size |
| `Jobs` | 1 row / job posting | `job_id` (PK) | FK `company_id` → Companies |
| `Sessions` | 1 row / user session | `session_id` (PK) | FK `user_id` → Users |
| `Applications` | 1 row / application | `application_id` (PK) | FK `user_id`, `job_id` |

### 2. Experimentation tables (raw, immutable event log)

| Table | Grain | Key columns | Notes |
|---|---|---|---|
| `Experiments` | 1 row / experiment | `experiment_id` (PK) | name, business_goal, primary/secondary/guardrail metrics, hypothesis, owner, dates, status |
| `ExperimentAssignments` | 1 row / (experiment, user) | `assignment_id` (PK), UNIQUE(`experiment_id`,`user_id`) | variant ∈ {control, treatment} |
| `ExperimentEvents` | 1 row / event | `event_id` (PK) | event_type ∈ {conversion, revenue, crash_rate, error_rate, cancellation_rate, refund_rate, bounce_rate}; event_value |

`ExperimentAssignments` and `ExperimentEvents` are the **source of truth**.
Every statistic in the platform is derived from these two tables — nothing
is hand-entered downstream.

### 3. Derived tables (rebuilt every `database.build_database()` run)

| Table | Derivation |
|---|---|
| `Conversions` | 1 row per assigned user; `converted = 1` iff a `conversion` event exists for that user in that experiment |
| `Revenue` | 1 row per assigned user; `revenue = SUM(event_value)` over `revenue` events (0 if none) |
| `Retention` | Proxy: `retained_d7` = same flag as `Conversions.converted` (documented limitation — see below) |
| `Errors` | 1 row per assigned user; `error_count` = count of `error_rate` events |

These tables are `DROP`+rebuilt from raw events every pipeline run
(`materialize_derived_tables()` in `database.py`), so they can never drift
from the raw log.

### 4. Results / audit tables (written by the engines, append-only)

| Table | Written by | Purpose |
|---|---|---|
| `Guardrails` | `guardrails.py` | Every guardrail evaluation (control/treatment rate, relative change, regression flag, p-value, timestamp) |
| `ExperimentLogs` | `experiment_logger.py` | The experiment learning log: decision, reasoning, lessons learned, next experiment |

## Known modeling simplifications (documented, not hidden)

- **Retention proxy**: this dataset does not simulate multi-week return
  visits, so `retention_d7` is currently a proxy equal to the conversion
  flag. In a real production system this would instead be computed from a
  `Sessions`-based "returned N days after assignment" query — the SQL
  shape for that is included as a template in `sql/experiment_queries.sql`
  guardrail query, ready to be pointed at real session recurrence data.
- **`application_success_rate`** is generated in the raw event stream as
  `application_success_rate_fail` (a failure flag) but is not yet wired
  into `guardrails.py`'s event-type map (`GUARDRAIL_EVENT_TYPES`) — the
  engine logs a warning and skips it rather than fabricating a number.
  This is intentional: **the validation policy in this project is "flag
  missing data instead of estimating it."**

## Indexes

Every foreign key column has a supporting index (see `create_tables.sql`),
plus composite indexes on `(experiment_id, variant)` and
`(experiment_id, event_type)` for the hot query paths used by the
statistics and guardrail engines.

## Constraints

- `CHECK` constraints enforce closed enums (`variant`, `device`, `status`,
  `decision`, etc.) at the SQLite layer, not just in Python.
- `UNIQUE(experiment_id, user_id)` on `ExperimentAssignments` prevents a
  user from being double-bucketed into both arms of the same experiment.

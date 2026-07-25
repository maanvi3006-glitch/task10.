-- =============================================================================
-- PlaceMux Growth Experimentation Analytics Platform
-- experiment_queries.sql — reference SQL for every metric on the dashboard
-- Every metric in statistics.py / guardrails.py is a pandas re-implementation
-- of one of these queries; this file is the SQL "source of truth" referenced
-- by validation.py METRIC_METADATA and the Validation page of the dashboard.
-- =============================================================================

-- Traffic split / assignment counts -------------------------------------------
SELECT variant, COUNT(*) AS n
FROM ExperimentAssignments
WHERE experiment_id = :experiment_id
GROUP BY variant;

-- Primary metric: application conversion rate ---------------------------------
SELECT variant,
       COUNT(*)                          AS n_users,
       SUM(converted)                    AS n_converted,
       AVG(converted) * 1.0              AS conversion_rate
FROM Conversions
WHERE experiment_id = :experiment_id
GROUP BY variant;

-- Revenue per user (0 for non-purchasers) --------------------------------------
SELECT variant,
       COUNT(*)          AS n_users,
       SUM(revenue)       AS total_revenue,
       AVG(revenue)       AS revenue_per_user
FROM Revenue
WHERE experiment_id = :experiment_id
GROUP BY variant;

-- D7 retention proxy ------------------------------------------------------------
SELECT variant, AVG(retained_d7) AS retention_rate
FROM Retention
WHERE experiment_id = :experiment_id
GROUP BY variant;

-- Guardrail metric rate (generic template — event_type parameterized) ---------
SELECT ea.variant,
       COUNT(DISTINCT ev.user_id) * 1.0 / COUNT(DISTINCT ea.user_id) AS metric_rate
FROM ExperimentAssignments ea
LEFT JOIN ExperimentEvents ev
       ON ev.experiment_id = ea.experiment_id
      AND ev.user_id = ea.user_id
      AND ev.event_type = :event_type
WHERE ea.experiment_id = :experiment_id
GROUP BY ea.variant;

-- Guardrail: crash rate ---------------------------------------------------------
SELECT ea.variant,
       COUNT(DISTINCT ev.user_id) * 1.0 / COUNT(DISTINCT ea.user_id) AS crash_rate
FROM ExperimentAssignments ea
LEFT JOIN ExperimentEvents ev
       ON ev.experiment_id = ea.experiment_id AND ev.user_id = ea.user_id
      AND ev.event_type = 'crash_rate'
WHERE ea.experiment_id = :experiment_id
GROUP BY ea.variant;

-- Guardrail: cancellation rate ---------------------------------------------------
SELECT ea.variant,
       COUNT(DISTINCT ev.user_id) * 1.0 / COUNT(DISTINCT ea.user_id) AS cancellation_rate
FROM ExperimentAssignments ea
LEFT JOIN ExperimentEvents ev
       ON ev.experiment_id = ea.experiment_id AND ev.user_id = ea.user_id
      AND ev.event_type = 'cancellation_rate'
WHERE ea.experiment_id = :experiment_id
GROUP BY ea.variant;

-- SRM: observed vs expected allocation --------------------------------------
SELECT variant, COUNT(*) AS observed_n
FROM ExperimentAssignments
WHERE experiment_id = :experiment_id
GROUP BY variant;
-- expected_n per arm = SUM(observed_n) * expected_split (0.5 by default),
-- compared via chi-square goodness-of-fit test in srm_checker.py

-- Experiment metadata -----------------------------------------------------------
SELECT experiment_id, experiment_name, business_goal, primary_metric,
       secondary_metrics, guardrail_metrics, hypothesis, owner,
       start_date, end_date, decision_date, status
FROM Experiments
WHERE experiment_id = :experiment_id;

-- Experiment log / history --------------------------------------------------
SELECT experiment_id, experiment_name, owner, objective, hypothesis,
       primary_metric_result, decision, reasoning, lessons_learned,
       next_experiment, logged_at
FROM ExperimentLogs
ORDER BY logged_at DESC;

-- Guardrail evaluation history ------------------------------------------------
SELECT experiment_id, metric_name, control_rate, treatment_rate,
       relative_change, is_regression, p_value, evaluated_at
FROM Guardrails
WHERE experiment_id = :experiment_id
ORDER BY evaluated_at DESC;

-- Conversion trend by day (for trend charts) ------------------------------------
SELECT DATE(ev.event_ts) AS event_date,
       ev.variant,
       COUNT(*) AS conversions
FROM ExperimentEvents ev
WHERE ev.experiment_id = :experiment_id AND ev.event_type = 'conversion'
GROUP BY DATE(ev.event_ts), ev.variant
ORDER BY event_date;

-- Revenue trend by day ------------------------------------------------------------
SELECT DATE(ev.event_ts) AS event_date,
       ev.variant,
       SUM(ev.event_value) AS daily_revenue
FROM ExperimentEvents ev
WHERE ev.experiment_id = :experiment_id AND ev.event_type = 'revenue'
GROUP BY DATE(ev.event_ts), ev.variant
ORDER BY event_date;

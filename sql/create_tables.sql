-- =============================================================================
-- PlaceMux Growth Experimentation Analytics Platform
-- create_tables.sql — normalized schema with PK/FK constraints and indexes
-- =============================================================================
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Core marketplace tables
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS Users;
CREATE TABLE Users (
    user_id        INTEGER PRIMARY KEY,
    signup_date    TEXT NOT NULL,
    country        TEXT NOT NULL,
    device         TEXT NOT NULL CHECK (device IN ('android','ios','web')),
    plan           TEXT NOT NULL CHECK (plan IN ('free','premium'))
);
CREATE INDEX idx_users_signup_date ON Users(signup_date);
CREATE INDEX idx_users_country ON Users(country);

DROP TABLE IF EXISTS Companies;
CREATE TABLE Companies (
    company_id     INTEGER PRIMARY KEY,
    company_name   TEXT NOT NULL,
    industry       TEXT NOT NULL,
    company_size   TEXT NOT NULL
);

DROP TABLE IF EXISTS Jobs;
CREATE TABLE Jobs (
    job_id         INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL,
    title          TEXT NOT NULL,
    category       TEXT NOT NULL,
    posted_date    TEXT NOT NULL,
    is_remote      INTEGER NOT NULL CHECK (is_remote IN (0,1)),
    FOREIGN KEY (company_id) REFERENCES Companies(company_id)
);
CREATE INDEX idx_jobs_company ON Jobs(company_id);
CREATE INDEX idx_jobs_category ON Jobs(category);

DROP TABLE IF EXISTS Sessions;
CREATE TABLE Sessions (
    session_id     INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    session_ts     TEXT NOT NULL,
    duration_sec   REAL NOT NULL CHECK (duration_sec >= 0),
    device         TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES Users(user_id)
);
CREATE INDEX idx_sessions_user ON Sessions(user_id);
CREATE INDEX idx_sessions_ts ON Sessions(session_ts);

DROP TABLE IF EXISTS Applications;
CREATE TABLE Applications (
    application_id INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    job_id         INTEGER NOT NULL,
    applied_date   TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('submitted','viewed','shortlisted','rejected','hired')),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (job_id) REFERENCES Jobs(job_id)
);
CREATE INDEX idx_applications_user ON Applications(user_id);
CREATE INDEX idx_applications_job ON Applications(job_id);
CREATE INDEX idx_applications_status ON Applications(status);

-- -----------------------------------------------------------------------------
-- Experimentation tables
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS Experiments;
CREATE TABLE Experiments (
    experiment_id      TEXT PRIMARY KEY,
    experiment_name    TEXT NOT NULL,
    business_goal       TEXT NOT NULL,
    primary_metric     TEXT NOT NULL,
    secondary_metrics  TEXT,
    guardrail_metrics  TEXT,
    hypothesis         TEXT NOT NULL,
    owner              TEXT NOT NULL,
    start_date         TEXT NOT NULL,
    end_date           TEXT NOT NULL,
    decision_date      TEXT,
    status             TEXT NOT NULL CHECK (status IN ('running','concluded','paused'))
);

DROP TABLE IF EXISTS ExperimentAssignments;
CREATE TABLE ExperimentAssignments (
    assignment_id  TEXT PRIMARY KEY,
    experiment_id  TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    variant        TEXT NOT NULL CHECK (variant IN ('control','treatment')),
    assigned_ts    TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES Experiments(experiment_id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    UNIQUE (experiment_id, user_id)
);
CREATE INDEX idx_assignments_experiment ON ExperimentAssignments(experiment_id);
CREATE INDEX idx_assignments_variant ON ExperimentAssignments(experiment_id, variant);

DROP TABLE IF EXISTS ExperimentEvents;
CREATE TABLE ExperimentEvents (
    event_id       TEXT PRIMARY KEY,
    experiment_id  TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    variant        TEXT NOT NULL CHECK (variant IN ('control','treatment')),
    event_type     TEXT NOT NULL,
    event_value    REAL NOT NULL,
    event_ts       TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES Experiments(experiment_id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id)
);
CREATE INDEX idx_events_experiment_type ON ExperimentEvents(experiment_id, event_type);
CREATE INDEX idx_events_variant ON ExperimentEvents(experiment_id, variant);

-- Derived/materialized convenience views (rebuilt by database.py) ------------
DROP TABLE IF EXISTS Conversions;
CREATE TABLE Conversions (
    experiment_id  TEXT NOT NULL,
    variant        TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    converted      INTEGER NOT NULL CHECK (converted IN (0,1)),
    PRIMARY KEY (experiment_id, user_id)
);

DROP TABLE IF EXISTS Revenue;
CREATE TABLE Revenue (
    experiment_id  TEXT NOT NULL,
    variant        TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    revenue        REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (experiment_id, user_id)
);

DROP TABLE IF EXISTS Retention;
CREATE TABLE Retention (
    experiment_id  TEXT NOT NULL,
    variant        TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    retained_d7    INTEGER NOT NULL CHECK (retained_d7 IN (0,1)),
    PRIMARY KEY (experiment_id, user_id)
);

DROP TABLE IF EXISTS Errors;
CREATE TABLE Errors (
    experiment_id  TEXT NOT NULL,
    variant        TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    error_count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (experiment_id, user_id)
);

DROP TABLE IF EXISTS Guardrails;
CREATE TABLE Guardrails (
    guardrail_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id      TEXT NOT NULL,
    metric_name        TEXT NOT NULL,
    control_rate       REAL NOT NULL,
    treatment_rate     REAL NOT NULL,
    relative_change    REAL NOT NULL,
    is_regression      INTEGER NOT NULL CHECK (is_regression IN (0,1)),
    p_value            REAL,
    evaluated_at       TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES Experiments(experiment_id)
);
CREATE INDEX idx_guardrails_experiment ON Guardrails(experiment_id);

DROP TABLE IF EXISTS ExperimentLogs;
CREATE TABLE ExperimentLogs (
    log_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id      TEXT NOT NULL,
    experiment_name    TEXT NOT NULL,
    owner              TEXT NOT NULL,
    objective          TEXT NOT NULL,
    hypothesis         TEXT NOT NULL,
    primary_metric_result TEXT,
    decision           TEXT NOT NULL CHECK (decision IN ('Ship','No Ship','Continue','Pause','Rollback')),
    reasoning          TEXT NOT NULL,
    lessons_learned    TEXT,
    next_experiment    TEXT,
    logged_at          TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES Experiments(experiment_id)
);
CREATE INDEX idx_logs_experiment ON ExperimentLogs(experiment_id);

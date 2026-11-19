-- Initial schema (SPEC §2). JSON columns hold validated Pydantic dumps.
-- Timestamps are ISO 8601 strings; `occurred_at_utc` is normalized to UTC
-- so period windows can be compared as text.

CREATE TABLE policies (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE policy_versions (
    policy_id     INTEGER NOT NULL REFERENCES policies (id),
    version       INTEGER NOT NULL CHECK (version >= 1),
    text          TEXT NOT NULL,
    status        TEXT NOT NULL
                  CHECK (status IN ('draft', 'compiling', 'compile_failed', 'active', 'retired')),
    compile_error TEXT,
    compile_meta  TEXT,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (policy_id, version)
);

-- At most one active version per policy.
CREATE UNIQUE INDEX one_active_version
    ON policy_versions (policy_id) WHERE status = 'active';

CREATE TABLE employees (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    policy_id INTEGER REFERENCES policies (id)
);

CREATE TABLE rules (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id INTEGER NOT NULL,
    version   INTEGER NOT NULL,
    type      TEXT NOT NULL,
    params    TEXT NOT NULL,
    clause    TEXT NOT NULL,
    status    TEXT NOT NULL CHECK (status IN ('proposed', 'approved', 'rejected')),
    origin    TEXT NOT NULL CHECK (origin IN ('llm', 'manual')),
    flags     TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (policy_id, version) REFERENCES policy_versions (policy_id, version)
);

CREATE TABLE uncompilable (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id  INTEGER NOT NULL,
    version    INTEGER NOT NULL,
    clause     TEXT NOT NULL,
    reason     TEXT NOT NULL,
    categories TEXT NOT NULL,
    effect     TEXT NOT NULL CHECK (effect IN ('requires_review', 'informational')),
    status     TEXT NOT NULL CHECK (status IN ('proposed', 'confirmed')),
    FOREIGN KEY (policy_id, version) REFERENCES policy_versions (policy_id, version)
);

CREATE TABLE expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     TEXT NOT NULL REFERENCES employees (id),
    amount_minor    INTEGER NOT NULL CHECK (amount_minor > 0),
    currency        TEXT NOT NULL,
    category        TEXT NOT NULL,
    merchant        TEXT,
    occurred_at     TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    justification   TEXT,
    pre_approval_id TEXT,
    status          TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'rejected')),
    created_at      TEXT NOT NULL
);

CREATE INDEX expenses_by_period
    ON expenses (employee_id, category, occurred_at_utc);

CREATE TABLE decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id     INTEGER UNIQUE REFERENCES expenses (id),
    employee_id    TEXT NOT NULL,
    policy_id      INTEGER NOT NULL,
    policy_version INTEGER NOT NULL,
    outcome        TEXT NOT NULL,
    reasons        TEXT NOT NULL,
    warnings       TEXT NOT NULL,
    evaluated_at   TEXT NOT NULL
);

CREATE TABLE idempotency_records (
    key          TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    status_code  INTEGER NOT NULL,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Data model integrity (SPEC §2, §6, §12a).
-- SQLite cannot change a PRIMARY KEY or a NOT NULL constraint in place, so the
-- two affected tables are rebuilt: create the new table, copy every row, drop
-- the old one, rename. Neither table is referenced by a foreign key, and their
-- only indexes are the implicit PRIMARY KEY / UNIQUE ones, which the new
-- definitions recreate. The runner applies this file in one transaction, so a
-- row that violates the new constraints aborts the whole migration.

-- 1. Who loaded the policy text. NULL for versions created before this column.

ALTER TABLE policy_versions ADD COLUMN created_by TEXT;

-- 2. Only submitted expenses persist a decision (checks store nothing),
--    so every stored decision belongs to an expense.

CREATE TABLE decisions_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id     INTEGER NOT NULL UNIQUE REFERENCES expenses (id),
    employee_id    TEXT NOT NULL,
    policy_id      INTEGER NOT NULL,
    policy_version INTEGER NOT NULL,
    outcome        TEXT NOT NULL,
    reasons        TEXT NOT NULL,
    warnings       TEXT NOT NULL,
    evaluated_at   TEXT NOT NULL
);

INSERT INTO decisions_new (id, expense_id, employee_id, policy_id, policy_version,
                           outcome, reasons, warnings, evaluated_at)
SELECT id, expense_id, employee_id, policy_id, policy_version,
       outcome, reasons, warnings, evaluated_at
FROM decisions;

-- Keep the AUTOINCREMENT counter, so ids are never reused.
DELETE FROM sqlite_sequence WHERE name = 'decisions_new';
INSERT INTO sqlite_sequence (name, seq)
SELECT 'decisions_new', seq FROM sqlite_sequence WHERE name = 'decisions';

DROP TABLE decisions;
ALTER TABLE decisions_new RENAME TO decisions;

-- 3. Idempotency keys are scoped per acting user: two users may send the same key.
--    `actor_id` has no foreign key, like the audit columns (see 002). Existing
--    records are stored 201 submit bodies, and a user only submits their own
--    expenses, so the actor is the expense's employee.

CREATE TABLE idempotency_records_new (
    actor_id     TEXT NOT NULL,
    key          TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code  INTEGER NOT NULL,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (actor_id, key)
);

INSERT INTO idempotency_records_new (actor_id, key, request_hash, status_code,
                                     response, created_at)
SELECT json_extract(response, '$.expense.employee_id'), key, request_hash,
       status_code, response, created_at
FROM idempotency_records;

DROP TABLE idempotency_records;
ALTER TABLE idempotency_records_new RENAME TO idempotency_records;

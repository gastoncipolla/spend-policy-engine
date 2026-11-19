-- Roles, demo identity and audit fields (SPEC §12a).
-- `roles` is a JSON list of role codes. `token` is the demo bearer token.
-- Audit columns hold the actor's user id; they have no foreign key on purpose,
-- so the audit trail never depends on the user row still existing.

ALTER TABLE employees ADD COLUMN roles TEXT NOT NULL DEFAULT '["employee"]';
ALTER TABLE employees ADD COLUMN manager_id TEXT REFERENCES employees (id);
ALTER TABLE employees ADD COLUMN token TEXT;

CREATE UNIQUE INDEX employees_by_token ON employees (token) WHERE token IS NOT NULL;
CREATE INDEX employees_by_manager ON employees (manager_id);

ALTER TABLE rules ADD COLUMN reviewed_by TEXT;
ALTER TABLE rules ADD COLUMN reviewed_at TEXT;

ALTER TABLE uncompilable ADD COLUMN classified_by TEXT;
ALTER TABLE uncompilable ADD COLUMN classified_at TEXT;

ALTER TABLE policy_versions ADD COLUMN activated_by TEXT;
ALTER TABLE policy_versions ADD COLUMN activated_at TEXT;

ALTER TABLE expenses ADD COLUMN resolved_by TEXT;
ALTER TABLE expenses ADD COLUMN resolved_at TEXT;

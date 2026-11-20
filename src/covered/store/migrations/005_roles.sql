-- Roles catalog and employee_roles (SPEC §2, §12a).
-- Roles move from a JSON list in `employees.roles` to a reference table and a
-- link table, so the database enforces the catalog. `employees` is rebuilt to
-- drop the old column, with the same recipe as 004: create the new table, copy
-- every row, drop the old one, rename, recreate its indexes. The runner applies
-- this file in one transaction with foreign keys checked at the end, so a row
-- that violates the new constraints aborts the whole migration.

-- 1. The catalog. Reference data, not demo data: every database needs it.
--    It must match the `Role` enum in store/records.py (a test checks it).

CREATE TABLE roles (
    code        TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

INSERT INTO roles (code, description) VALUES
    ('employee', 'Spends: checks and submits their own expenses'),
    ('manager', 'Resolves the pending expenses of their direct reports'),
    ('finance', 'Administers policies and resolves anyone''s pending expenses');

-- 2. Who has which role. A user can have several roles.

CREATE TABLE employee_roles (
    employee_id TEXT NOT NULL REFERENCES employees (id),
    role        TEXT NOT NULL REFERENCES roles (code),
    PRIMARY KEY (employee_id, role)
);

CREATE INDEX employee_roles_by_role ON employee_roles (role);

-- An unknown role code in the old JSON fails the foreign key check at the end.
INSERT INTO employee_roles (employee_id, role)
SELECT DISTINCT employees.id, role.value
FROM employees, json_each(employees.roles) AS role;

-- Before 005 nothing required a manager to have the manager role (the demo's
-- fede, finance, manages bruno and diego). Keep every reporting line: whoever
-- has reports gets the manager role, so the invariant below holds.
INSERT OR IGNORE INTO employee_roles (employee_id, role)
SELECT DISTINCT manager_id, 'manager'
FROM employees
WHERE manager_id IS NOT NULL;

-- 3. Rebuild employees without the JSON column.

CREATE TABLE employees_new (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    policy_id  INTEGER REFERENCES policies (id),
    manager_id TEXT REFERENCES employees (id),
    token      TEXT
);

-- 4. A manager_id must point to a user with the manager role. Created before
--    the copy, so existing rows are checked too; the trigger follows the rename.

CREATE TRIGGER employees_manager_has_role_on_insert
BEFORE INSERT ON employees_new
WHEN NEW.manager_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM employee_roles
    WHERE employee_id = NEW.manager_id AND role = 'manager'
)
BEGIN
    SELECT RAISE(ABORT, 'manager_id must reference a user with the manager role');
END;

CREATE TRIGGER employees_manager_has_role_on_update
BEFORE UPDATE OF manager_id ON employees_new
WHEN NEW.manager_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM employee_roles
    WHERE employee_id = NEW.manager_id AND role = 'manager'
)
BEGIN
    SELECT RAISE(ABORT, 'manager_id must reference a user with the manager role');
END;

INSERT INTO employees_new (id, name, policy_id, manager_id, token)
SELECT id, name, policy_id, manager_id, token
FROM employees;

DROP TABLE employees;
ALTER TABLE employees_new RENAME TO employees;

CREATE UNIQUE INDEX employees_by_token ON employees (token) WHERE token IS NOT NULL;
CREATE INDEX employees_by_manager ON employees (manager_id);

-- 5. A manager keeps the manager role while someone still reports to them.

CREATE TRIGGER employee_roles_keep_manager_with_reports_on_delete
BEFORE DELETE ON employee_roles
WHEN OLD.role = 'manager' AND EXISTS (
    SELECT 1 FROM employees WHERE manager_id = OLD.employee_id
)
BEGIN
    SELECT RAISE(ABORT, 'cannot remove the manager role from a user who has reports');
END;

CREATE TRIGGER employee_roles_keep_manager_with_reports_on_update
BEFORE UPDATE ON employee_roles
WHEN OLD.role = 'manager'
    AND (NEW.role <> 'manager' OR NEW.employee_id <> OLD.employee_id)
    AND EXISTS (SELECT 1 FROM employees WHERE manager_id = OLD.employee_id)
BEGIN
    SELECT RAISE(ABORT, 'cannot remove the manager role from a user who has reports');
END;

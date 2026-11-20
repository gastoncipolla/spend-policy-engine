-- Demo users (SPEC §9, §12a). Fictional people, demo-only tokens.
-- This is demo data, not reference data: it is NOT a migration, so it never
-- lands in a real database. Only `covered seed` runs it, on a fresh database,
-- inside one transaction. Policies are created afterwards through the services.
-- Managers come before their reports: manager_id must point to an existing user
-- with the manager role (foreign key + trigger from migration 005). That is why
-- fede, who manages bruno and diego, has the manager role as well as finance.

INSERT INTO employees (id, name, policy_id, manager_id, token) VALUES
    ('fede', 'Fede', NULL, NULL, 'demo-fede'),
    -- A second finance user, so each finance user's own pending expenses can be
    -- resolved by someone else (separation of duties).
    ('gabi', 'Gabi', NULL, NULL, 'demo-gabi');

INSERT INTO employee_roles (employee_id, role) VALUES
    ('fede', 'employee'), ('fede', 'finance'), ('fede', 'manager'),
    ('gabi', 'employee'), ('gabi', 'finance');

INSERT INTO employees (id, name, policy_id, manager_id, token) VALUES
    ('bruno', 'Bruno', NULL, 'fede', 'demo-bruno'),
    ('diego', 'Diego', NULL, 'fede', 'demo-diego');

INSERT INTO employee_roles (employee_id, role) VALUES
    ('bruno', 'employee'), ('bruno', 'manager'),
    ('diego', 'employee'), ('diego', 'manager');

INSERT INTO employees (id, name, policy_id, manager_id, token) VALUES
    ('ana', 'Ana', NULL, 'bruno', 'demo-ana'),
    ('carla', 'Carla', NULL, 'diego', 'demo-carla');

INSERT INTO employee_roles (employee_id, role) VALUES
    ('ana', 'employee'),
    ('carla', 'employee');

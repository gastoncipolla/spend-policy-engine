"""Migration 005 moves roles into tables without losing data, and the database
enforces the roles catalog and the manager invariant."""

import sqlite3
from importlib import resources

import pytest

from covered.store import employees
from covered.store.db import _statements, connect, migrate, open_database
from covered.store.records import Role

BEFORE_005 = [
    "001_initial.sql",
    "002_roles_and_audit.sql",
    "003_compiling_since.sql",
    "004_data_model_integrity.sql",
]


def _database_before_005(path: str) -> sqlite3.Connection:
    """The schema as it was before 005, applied the way the runner did then."""
    conn = connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    folder = resources.files("covered.store") / "migrations"
    for name in BEFORE_005:
        for statement in _statements((folder / name).read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations VALUES (?, 'then')", (name,))
    return conn


def _seed_old_rows(conn: sqlite3.Connection, fede_roles: str) -> None:
    conn.executescript(
        f"""
        INSERT INTO policies (id, name) VALUES (1, 'Sales');
        INSERT INTO employees (id, name, policy_id, roles, manager_id, token) VALUES
            ('fede', 'Fede', 1, '{fede_roles}', NULL, 'demo-fede'),
            ('bruno', 'Bruno', 1, '["employee", "manager"]', 'fede', 'demo-bruno'),
            ('ana', 'Ana', 1, '["employee"]', 'bruno', NULL);
        INSERT INTO expenses (id, employee_id, amount_minor, currency, category,
                              occurred_at, occurred_at_utc, status, created_at)
            VALUES (1, 'ana', 6000, 'USD', 'meals', 't', 't', 'approved', 't');
        """
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    return open_database(":memory:")


def test_migration_005_keeps_users_roles_and_indexes(tmp_path):
    conn = _database_before_005(str(tmp_path / "old.db"))
    _seed_old_rows(conn, '["employee", "finance", "manager"]')

    assert migrate(conn) == ["005_roles.sql"]

    staff = {e.id: (e.roles, e.manager_id) for e in employees.list_employees(conn)}
    assert staff == {
        "fede": ({Role.EMPLOYEE, Role.FINANCE, Role.MANAGER}, None),
        "bruno": ({Role.EMPLOYEE, Role.MANAGER}, "fede"),
        "ana": ({Role.EMPLOYEE}, "bruno"),
    }
    assert employees.get_employee_by_token(conn, "demo-bruno").id == "bruno"
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(employees)")}
    assert columns == {"id", "name", "policy_id", "manager_id", "token"}
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(employees)")}
    assert {"employees_by_token", "employees_by_manager"} <= indexes
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # Children still point at the rebuilt table; the token stays unique.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM employees WHERE id = 'ana'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE employees SET token = 'demo-fede' WHERE id = 'ana'")


def test_migration_005_gives_the_manager_role_to_whoever_has_reports(tmp_path):
    conn = _database_before_005(str(tmp_path / "old.db"))
    _seed_old_rows(conn, '["employee", "finance"]')  # fede manages bruno

    assert migrate(conn) == ["005_roles.sql"]

    fede = employees.get_employee(conn, "fede")
    assert fede.roles == {Role.EMPLOYEE, Role.FINANCE, Role.MANAGER}
    assert employees.get_employee(conn, "bruno").manager_id == "fede"


def test_migration_005_aborts_on_an_unknown_role(tmp_path):
    conn = _database_before_005(str(tmp_path / "old.db"))
    conn.execute(
        "INSERT INTO employees (id, name, roles) VALUES ('x', 'X', '[\"admin\"]')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="foreign key"):
        migrate(conn)

    # Rolled back: the old column is still there and 005 is not recorded.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(employees)")}
    assert "roles" in columns
    names = [row[0] for row in conn.execute("SELECT name FROM schema_migrations")]
    assert "005_roles.sql" not in names
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_roles_table_matches_the_role_enum(conn):
    assert employees.list_role_codes(conn) == {role.value for role in Role}


def test_unknown_role_is_rejected(conn):
    employees.insert_employee(conn, "ana", "Ana", None)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO employee_roles VALUES ('ana', 'admin')")


def test_manager_id_must_point_to_a_manager(conn):
    employees.insert_employee(conn, "ana", "Ana", None)
    employees.insert_employee(conn, "bruno", "Bruno", None)

    with pytest.raises(sqlite3.IntegrityError, match="manager role"):
        employees.insert_employee(conn, "carla", "Carla", None, manager_id="ana")
    with pytest.raises(sqlite3.IntegrityError, match="manager role"):
        conn.execute("UPDATE employees SET manager_id = 'ana' WHERE id = 'bruno'")

    conn.execute("INSERT INTO employee_roles VALUES ('ana', 'manager')")
    conn.execute("UPDATE employees SET manager_id = 'ana' WHERE id = 'bruno'")
    assert employees.get_employee(conn, "bruno").manager_id == "ana"


def test_manager_role_stays_while_the_manager_has_reports(conn):
    employees.insert_employee(conn, "bruno", "Bruno", None, roles=list(Role))
    employees.insert_employee(conn, "ana", "Ana", None, manager_id="bruno")

    with pytest.raises(sqlite3.IntegrityError, match="has reports"):
        conn.execute(
            "DELETE FROM employee_roles WHERE employee_id = 'bruno' AND role = 'manager'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="has reports"):
        conn.execute(
            "UPDATE employee_roles SET role = 'finance'"
            " WHERE employee_id = 'bruno' AND role = 'manager'"
        )
    # Other roles can go; and once nobody reports to bruno, so can manager.
    conn.execute(
        "DELETE FROM employee_roles WHERE employee_id = 'bruno' AND role = 'finance'"
    )
    conn.execute("UPDATE employees SET manager_id = NULL WHERE id = 'ana'")
    conn.execute(
        "DELETE FROM employee_roles WHERE employee_id = 'bruno' AND role = 'manager'"
    )
    assert employees.get_employee(conn, "bruno").roles == {Role.EMPLOYEE}


def test_migrations_create_no_users(conn):
    """Demo users live in seeds/demo.sql, never in a migration."""
    assert employees.list_employees(conn) == []

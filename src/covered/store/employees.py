"""Repository: employees (users), their roles, manager and demo token.

Roles live in `employee_roles` (catalog in `roles`); reads fold them back into
the record's `roles` set.
"""

import json
import sqlite3
from collections.abc import Collection

from covered.store.records import Employee, Role

_SELECT = (
    "SELECT id, name, policy_id, manager_id,"
    " (SELECT json_group_array(role) FROM employee_roles"
    "  WHERE employee_id = employees.id) AS roles"
    " FROM employees"
)


def insert_employee(
    conn: sqlite3.Connection,
    employee_id: str,
    name: str,
    policy_id: int | None,
    *,
    roles: Collection[Role] = (Role.EMPLOYEE,),
    manager_id: str | None = None,
    token: str | None = None,
) -> Employee:
    """Insert the user and their roles. Call inside a transaction."""
    conn.execute(
        "INSERT INTO employees (id, name, policy_id, manager_id, token)"
        " VALUES (?, ?, ?, ?, ?)",
        (employee_id, name, policy_id, manager_id, token),
    )
    conn.executemany(
        "INSERT INTO employee_roles (employee_id, role) VALUES (?, ?)",
        [(employee_id, role) for role in sorted({Role(role) for role in roles})],
    )
    return get_employee(conn, employee_id)


def get_employee(conn: sqlite3.Connection, employee_id: str) -> Employee | None:
    row = conn.execute(f"{_SELECT} WHERE id = ?", (employee_id,)).fetchone()
    return _employee(row) if row else None


def get_employee_by_token(conn: sqlite3.Connection, token: str) -> Employee | None:
    row = conn.execute(f"{_SELECT} WHERE token = ?", (token,)).fetchone()
    return _employee(row) if row else None


def get_token(conn: sqlite3.Connection, employee_id: str) -> str | None:
    row = conn.execute(
        "SELECT token FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return row["token"] if row else None


def list_employees(conn: sqlite3.Connection) -> list[Employee]:
    rows = conn.execute(f"{_SELECT} ORDER BY name")
    return [_employee(row) for row in rows]


def list_role_codes(conn: sqlite3.Connection) -> set[str]:
    """The roles catalog as stored (reference data from migration 005)."""
    return {row["code"] for row in conn.execute("SELECT code FROM roles")}


def set_policy(
    conn: sqlite3.Connection, employee_id: str, policy_id: int | None
) -> None:
    conn.execute(
        "UPDATE employees SET policy_id = ? WHERE id = ?", (policy_id, employee_id)
    )


def _employee(row: sqlite3.Row) -> Employee:
    data = dict(row)
    data["roles"] = frozenset(json.loads(data["roles"]))
    return Employee(**data)

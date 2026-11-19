"""Repository: employees (users), their roles, manager and demo token."""

import json
import sqlite3
from collections.abc import Collection

from covered.store.records import Employee, Role

_COLUMNS = "id, name, policy_id, roles, manager_id"


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
    conn.execute(
        "INSERT INTO employees (id, name, policy_id, roles, manager_id, token)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (employee_id, name, policy_id, _roles_json(roles), manager_id, token),
    )
    return get_employee(conn, employee_id)


def get_employee(conn: sqlite3.Connection, employee_id: str) -> Employee | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return _employee(row) if row else None


def get_employee_by_token(conn: sqlite3.Connection, token: str) -> Employee | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM employees WHERE token = ?", (token,)
    ).fetchone()
    return _employee(row) if row else None


def get_token(conn: sqlite3.Connection, employee_id: str) -> str | None:
    row = conn.execute(
        "SELECT token FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return row["token"] if row else None


def list_employees(conn: sqlite3.Connection) -> list[Employee]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM employees ORDER BY name")
    return [_employee(row) for row in rows]


def set_policy(
    conn: sqlite3.Connection, employee_id: str, policy_id: int | None
) -> None:
    conn.execute(
        "UPDATE employees SET policy_id = ? WHERE id = ?", (policy_id, employee_id)
    )


def _roles_json(roles: Collection[Role]) -> str:
    return json.dumps(sorted(Role(role) for role in roles))


def _employee(row: sqlite3.Row) -> Employee:
    data = dict(row)
    data["roles"] = frozenset(json.loads(data["roles"]))
    return Employee(**data)

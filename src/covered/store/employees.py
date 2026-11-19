"""Repository: employees."""

import sqlite3

from covered.store.records import Employee


def insert_employee(
    conn: sqlite3.Connection, employee_id: str, name: str, policy_id: int | None
) -> Employee:
    conn.execute(
        "INSERT INTO employees (id, name, policy_id) VALUES (?, ?, ?)",
        (employee_id, name, policy_id),
    )
    return Employee(id=employee_id, name=name, policy_id=policy_id)


def get_employee(conn: sqlite3.Connection, employee_id: str) -> Employee | None:
    row = conn.execute(
        "SELECT * FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return Employee(**row) if row else None


def list_employees(conn: sqlite3.Connection) -> list[Employee]:
    return [
        Employee(**row) for row in conn.execute("SELECT * FROM employees ORDER BY name")
    ]

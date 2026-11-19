"""Use cases: employees."""

import sqlite3

from covered.domain.errors import NotFoundError
from covered.store import employees as employee_store
from covered.store import policies as policy_store
from covered.store.db import transaction
from covered.store.records import Employee


def create_employee(
    conn: sqlite3.Connection, employee_id: str, name: str, policy_id: int | None
) -> Employee:
    with transaction(conn):
        if policy_id is not None and policy_store.get_policy(conn, policy_id) is None:
            raise NotFoundError(f"policy {policy_id} not found")
        return employee_store.insert_employee(conn, employee_id, name, policy_id)


def list_employees(conn: sqlite3.Connection) -> list[Employee]:
    return employee_store.list_employees(conn)

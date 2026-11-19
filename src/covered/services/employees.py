"""Use cases: users (employees), identity and who sees whom (SPEC §12a).

`create_employee` and `assign_policy` are provisioning steps used by the seed
and by tests; no endpoint exposes them.
"""

import sqlite3
from collections.abc import Collection

from covered.domain.errors import NotFoundError, UnauthenticatedError
from covered.services import authz
from covered.services.authz import Actor
from covered.store import employees as employee_store
from covered.store import policies as policy_store
from covered.store.db import transaction
from covered.store.records import Employee, Role


def create_employee(
    conn: sqlite3.Connection,
    employee_id: str,
    name: str,
    policy_id: int | None,
    *,
    roles: Collection[Role] = (Role.EMPLOYEE,),
    manager_id: str | None = None,
    token: str | None = None,
) -> Employee:
    with transaction(conn):
        _require_policy(conn, policy_id)
        if manager_id is not None and not employee_store.get_employee(conn, manager_id):
            raise NotFoundError(f"manager {manager_id!r} not found")
        return employee_store.insert_employee(
            conn,
            employee_id,
            name,
            policy_id,
            roles=roles,
            manager_id=manager_id,
            token=token,
        )


def assign_policy(
    conn: sqlite3.Connection, employee_id: str, policy_id: int | None
) -> None:
    with transaction(conn):
        _require_policy(conn, policy_id)
        employee_store.set_policy(conn, employee_id, policy_id)


def authenticate(conn: sqlite3.Connection, token: str | None) -> Actor:
    """The user behind a demo bearer token. Missing or unknown → 401."""
    user = employee_store.get_employee_by_token(conn, token) if token else None
    if user is None:
        raise UnauthenticatedError("missing or unknown bearer token")
    return user


def act_as(conn: sqlite3.Connection, employee_id: str) -> Actor:
    """The user with this id, for the CLI's `--as` (demo identity, no login)."""
    user = employee_store.get_employee(conn, employee_id)
    if user is None:
        raise UnauthenticatedError(f"unknown user {employee_id!r}")
    return user


def demo_token(conn: sqlite3.Connection, employee_id: str) -> str | None:
    """The demo token behind the pages' "act as" selector."""
    return employee_store.get_token(conn, employee_id)


def demo_users(conn: sqlite3.Connection) -> list[Employee]:
    """Everyone, for the "act as" selector only (the demo has no login)."""
    return employee_store.list_employees(conn)


def list_employees(conn: sqlite3.Connection, actor: Actor) -> list[Employee]:
    """Self (employee), self + team (manager), everyone (finance)."""
    return [
        employee
        for employee in employee_store.list_employees(conn)
        if authz.can_see_employee(actor, employee)
    ]


def _require_policy(conn: sqlite3.Connection, policy_id: int | None) -> None:
    if policy_id is not None and policy_store.get_policy(conn, policy_id) is None:
        raise NotFoundError(f"policy {policy_id} not found")

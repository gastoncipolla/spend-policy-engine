"""Provisioning users: a manager_id must name a user with the manager role."""

import pytest

from covered.domain.errors import InvalidInputError, NotFoundError
from covered.services import employees
from covered.store.records import Role


def test_manager_must_exist(conn):
    with pytest.raises(NotFoundError):
        employees.create_employee(conn, "ana", "Ana", None, manager_id="nobody")


def test_manager_must_have_the_manager_role(conn):
    employees.create_employee(conn, "bea", "Bea", None)
    with pytest.raises(InvalidInputError, match="manager role"):
        employees.create_employee(conn, "ana", "Ana", None, manager_id="bea")
    assert employees.demo_users(conn) == [employees.act_as(conn, "bea")]


def test_report_of_a_manager_is_created(conn):
    employees.create_employee(
        conn, "bruno", "Bruno", None, roles=[Role.EMPLOYEE, Role.MANAGER]
    )
    ana = employees.create_employee(conn, "ana", "Ana", None, manager_id="bruno")
    assert (ana.roles, ana.manager_id) == ({Role.EMPLOYEE}, "bruno")

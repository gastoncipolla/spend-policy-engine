"""Fixtures for service tests: a file-backed DB and an active sample policy."""

import pytest
from service_builders import FINANCE, POLICY_TEXT, SAMPLE_RULES

from covered.services import employees, policies
from covered.store.db import open_database


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "covered.db")


@pytest.fixture
def conn(db_path):
    connection = open_database(db_path)
    yield connection
    connection.close()


@pytest.fixture
def sales(conn):
    """Policy "Sales" with version 1 active (manual rules) and employee "ana"."""
    policy = policies.create_policy(conn, FINANCE, "Sales")
    policies.create_version(conn, FINANCE, policy.id, POLICY_TEXT)
    for params, clause in SAMPLE_RULES:
        policies.add_manual_rule(conn, FINANCE, policy.id, 1, params, clause)
    policies.activate_version(conn, FINANCE, policy.id, 1)
    employees.create_employee(conn, "ana", "Ana", policy.id, token="t-ana")
    return policy


@pytest.fixture
def ana(conn, sales):
    """The actor "ana" (plain employee on the Sales policy)."""
    return employees.act_as(conn, "ana")

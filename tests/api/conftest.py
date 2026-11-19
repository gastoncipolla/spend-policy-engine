"""Fixtures for API tests: an app on a temp SQLite file with a fake compiler."""

import pytest
from api_builders import API_POLICY_TEXT, approve_all, fake_compiler
from fastapi.testclient import TestClient

from covered.api import create_app
from covered.services import employees
from covered.store.db import open_database


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "api.db")


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path, compiler=fake_compiler)) as test_client:
        yield test_client


@pytest.fixture
def db(db_path):
    """A direct connection for setup the API does not expose (employees)."""
    conn = open_database(db_path)
    yield conn
    conn.close()


@pytest.fixture
def draft(client):
    """Policy with a compiled (all proposed) version 1. Returns (policy_id, detail)."""
    policy = client.post("/policies", json={"name": "Sales"}).json()
    client.post(f"/policies/{policy['id']}/versions", json={"text": API_POLICY_TEXT})
    detail = client.post(f"/policies/{policy['id']}/versions/1/compile").json()
    return policy["id"], detail


@pytest.fixture
def active(client, db, draft):
    """Version 1 approved and active, with employee "ana" on it. Returns the policy id."""
    policy_id, detail = draft
    approve_all(client, detail)
    response = client.post(f"/policies/{policy_id}/versions/1/activate")
    assert response.status_code == 200, response.json()
    employees.create_employee(db, "ana", "Ana", policy_id)
    return policy_id

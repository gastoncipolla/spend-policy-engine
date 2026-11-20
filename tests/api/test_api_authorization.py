"""SPEC §12a over HTTP on the seeded demo: bearer tokens, 401/403/404, list filtering.

The full matrix is tested in the service layer (tests/services/test_authorization.py);
these tests prove every endpoint resolves the caller and maps the errors.
"""

import pytest
from fastapi.testclient import TestClient

from covered.api import create_app
from covered.compiler import MockProvider
from covered.services.provider_compiler import ProviderCompiler
from covered.services.seed import reset_database, seed

AIRFARE = {  # needs approval under both demo policies
    "amount_minor": 30000,
    "currency": "USD",
    "category": "airfare",
    "occurred_at": "2026-11-18T10:00:00-03:00",
}


def bearer(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer demo-{user}"}


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "demo.db")
    conn = reset_database(db_path)
    seed(conn)
    conn.close()
    app = create_app(db_path, compiler=ProviderCompiler(MockProvider()))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def pending(client):
    """One pending airfare per demo user: {user id: expense id}."""
    ids = {}
    for user in ("ana", "bruno", "carla", "diego", "fede"):
        response = client.post(
            "/expenses",
            json={**AIRFARE, "employee_id": user},
            headers={"Idempotency-Key": f"k-{user}", **bearer(user)},
        )
        assert response.json()["expense"]["status"] == "pending", response.json()
        ids[user] = response.json()["expense"]["id"]
    return ids


def _assert_error(response, status_code, code):
    assert response.status_code == status_code, response.json()
    assert response.json()["error"] == code and response.json()["message"]


ENDPOINTS = [
    ("GET", "/categories"),
    ("GET", "/employees"),
    ("GET", "/policies"),
    ("POST", "/policies"),
    ("GET", "/policies/1/versions/1"),
    ("POST", "/policies/1/versions"),
    ("POST", "/policies/1/versions/1/compile"),
    ("POST", "/policies/1/versions/1/rules"),
    ("PATCH", "/rules/1"),
    ("PATCH", "/uncompilable/1"),
    ("POST", "/policies/1/versions/1/activate"),
    ("POST", "/expenses/check"),
    ("POST", "/expenses"),
    ("GET", "/expenses"),
    ("GET", "/expenses/1"),
    ("POST", "/expenses/1/resolve"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        {"Authorization": "demo-ana"},
        {"Authorization": "Basic demo-ana"},
        {"Authorization": "Bearer "},
    ],
)
def test_missing_or_unknown_token_is_401(client, method, path, headers):
    response = client.request(method, path, headers=headers, json={})
    _assert_error(response, 401, "unauthenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("user", "visible"),
    [
        ("ana", {"ana"}),
        ("bruno", {"ana", "bruno"}),
        ("diego", {"carla", "diego"}),
        ("fede", {"ana", "bruno", "carla", "diego", "fede"}),
    ],
)
def test_lists_are_filtered_by_role(client, pending, user, visible):
    listed = client.get("/expenses", headers=bearer(user)).json()
    assert {item["expense"]["employee_id"] for item in listed} == visible
    people = client.get("/employees", headers=bearer(user)).json()
    # gabi (second finance user) has no expenses here but is visible to finance.
    expected_people = visible | {"gabi"} if user == "fede" else visible
    assert {person["id"] for person in people} == expected_people


def test_bola_another_employees_expense_is_404(client, pending):
    """Ana asks for Carla's expense: 404 not_found, as if it did not exist."""
    _assert_error(
        client.get(f"/expenses/{pending['carla']}", headers=bearer("ana")),
        404,
        "not_found",
    )
    _assert_error(
        client.post(
            f"/expenses/{pending['carla']}/resolve",
            json={"resolution": "approved"},
            headers=bearer("ana"),
        ),
        404,
        "not_found",
    )
    assert client.get(f"/expenses/{pending['ana']}", headers=bearer("ana")).json()[
        "expense"
    ]["employee_id"] == ("ana")
    assert client.get(f"/expenses/{pending['ana']}", headers=bearer("bruno")).is_success


@pytest.mark.parametrize("user", ["bruno", "fede"])
def test_self_approval_is_403_for_manager_and_finance(client, pending, user):
    response = client.post(
        f"/expenses/{pending[user]}/resolve",
        json={"resolution": "approved"},
        headers=bearer(user),
    )
    _assert_error(response, 403, "forbidden")
    assert "own expense" in response.json()["message"]


def test_manager_resolves_team_and_finance_resolves_managers_own(client, pending):
    by_manager = client.post(
        f"/expenses/{pending['ana']}/resolve",
        json={"resolution": "approved"},
        headers=bearer("bruno"),
    ).json()["expense"]
    assert (by_manager["status"], by_manager["resolved_by"]) == ("approved", "bruno")
    assert by_manager["resolved_at"]

    by_finance = client.post(
        f"/expenses/{pending['diego']}/resolve",
        json={"resolution": "rejected"},
        headers=bearer("fede"),
    ).json()["expense"]
    assert (by_finance["status"], by_finance["resolved_by"]) == ("rejected", "fede")


def test_submitting_for_someone_else_is_403(client):
    for path, extra in [
        ("/expenses/check", {}),
        ("/expenses", {"Idempotency-Key": "x"}),
    ]:
        response = client.post(
            path,
            json={**AIRFARE, "employee_id": "carla"},
            headers={**bearer("fede"), **extra},
        )
        _assert_error(response, 403, "forbidden")


@pytest.mark.parametrize("user", ["ana", "bruno"])
def test_policy_administration_is_403_for_non_finance(client, user):
    headers = bearer(user)
    calls = [
        ("POST", "/policies", {"name": "Mine"}),
        ("POST", "/policies/1/versions", {"text": "Meals are capped at USD 1."}),
        ("POST", "/policies/1/versions/1/compile", None),
        ("PATCH", "/rules/1", {"status": "rejected"}),
        ("PATCH", "/uncompilable/1", {"categories": ["*"], "effect": "informational"}),
        ("POST", "/policies/1/versions/1/activate", None),
    ]
    for method, path, body in calls:
        _assert_error(
            client.request(method, path, json=body, headers=headers), 403, "forbidden"
        )


def test_policy_reads_are_limited_to_own_policy(client):
    ana = bearer("ana")
    assert [p["name"] for p in client.get("/policies", headers=ana).json()] == ["Sales"]
    assert client.get("/policies/1/versions/1", headers=ana).is_success
    _assert_error(client.get("/policies/2/versions/1", headers=ana), 404, "not_found")
    finance = client.get("/policies", headers=bearer("fede")).json()
    assert [p["name"] for p in finance] == ["Sales", "Engineering"]


def test_audit_fields_are_exposed(client):
    detail = client.get("/policies/1/versions/1", headers=bearer("fede")).json()
    assert detail["activated_by"] == "fede" and detail["activated_at"]
    assert detail["created_by"] == "fede"
    assert {rule["reviewed_by"] for rule in detail["rules"]} == {"fede"}
    assert {item["classified_by"] for item in detail["uncompilable"]} == {"fede"}

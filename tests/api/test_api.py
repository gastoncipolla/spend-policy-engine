"""API tests (SPEC §12): envelope, policy lifecycle, idempotency, resolve, errors."""

import pytest
from api_builders import add_users, approve_all, bearer
from fastapi.testclient import TestClient

from covered.api import create_app
from covered.services import employees
from covered.store import policies as policy_store
from covered.store.db import open_database, transaction
from covered.store.records import VersionStatus

TAXI = {
    "employee_id": "ana",
    "amount_minor": 6000,
    "currency": "USD",
    "category": "ground_transport",
    "merchant": "Taxi Co",
    "occurred_at": "2026-11-18T10:00:00-03:00",
}


ANA = bearer("ana")


def _submit(client, key, **overrides):
    """Submit as ana (the expense's employee)."""
    return client.post(
        "/expenses", json={**TAXI, **overrides}, headers={"Idempotency-Key": key, **ANA}
    )


def _assert_error(response, status_code, code):
    assert response.status_code == status_code, response.json()
    body = response.json()
    assert body["error"] == code and body["message"]


# Catalog and envelope


def test_health_categories_and_employees(client):
    assert client.get("/health", headers={}).json() == {"status": "ok"}
    codes = [c["code"] for c in client.get("/categories").json()]
    assert codes[0] == "meals" and "other" in codes and len(codes) == 9
    assert client.get("/employees").json() == [
        {
            "id": "ana",
            "name": "Ana",
            "policy_id": None,
            "roles": ["employee"],
            "manager_id": None,
        },
        {
            "id": "fede",
            "name": "Fede",
            "policy_id": None,
            "roles": ["employee", "finance"],
            "manager_id": None,
        },
    ]
    assert [e["id"] for e in client.get("/employees", headers=ANA).json()] == ["ana"]


def test_unknown_route_and_resources_use_the_error_envelope(client):
    _assert_error(client.get("/nope"), 404, "not_found")
    _assert_error(client.get("/policies/9/versions/1"), 404, "not_found")
    _assert_error(
        client.patch("/rules/9", json={"status": "approved"}), 404, "not_found"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_minor": 60.5},
        {"amount_minor": "6000"},
        {"amount_minor": 0},
        {"amount_minor": 10**30},
        {"amount_minor": 10**12 + 1},
        {"currency": "EUR"},
        {"category": "spa"},
        {"occurred_at": "2026-11-18T10:00:00"},
    ],
)
def test_invalid_expense_is_a_validation_error(client, active, overrides):
    _assert_error(
        client.post("/expenses/check", json={**TAXI, **overrides}, headers=ANA),
        422,
        "validation_error",
    )


# Policy lifecycle


def test_compile_review_and_activate(client, draft):
    policy_id, detail = draft
    assert detail["status"] == "draft"
    assert {r["status"] for r in detail["rules"]} == {"proposed"}
    assert detail["rules"][0]["params"]["amount_minor"] == 20000
    assert detail["uncompilable"][0]["status"] == "proposed"

    approve_all(client, detail)
    activated = client.post(f"/policies/{policy_id}/versions/1/activate")
    assert activated.status_code == 200
    body = activated.json()
    assert body["status"] == "active"
    assert "ground_transport" not in body["uncovered_categories"]
    assert "other" in body["uncovered_categories"]

    listed = client.get("/policies").json()
    assert listed[0]["active_version"] == 1


def test_activation_blocked_while_rules_are_proposed(client, draft):
    policy_id, _ = draft
    _assert_error(
        client.post(f"/policies/{policy_id}/versions/1/activate"),
        409,
        "activation_blocked",
    )


def test_manual_rule_is_created_approved(client, draft):
    policy_id, _ = draft
    response = client.post(
        f"/policies/{policy_id}/versions/1/rules",
        json={
            "params": {"type": "prohibited_category", "category": "meals"},
            "clause": "Meals are capped at USD 50 per expense.",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "approved"
    assert response.json()["origin"] == "manual"


def test_rule_params_are_validated(client, draft):
    _, detail = draft
    rule_id = detail["rules"][0]["id"]
    bad = {"params": {"type": "max_amount", "category": "meals", "amount_minor": -1}}
    _assert_error(client.patch(f"/rules/{rule_id}", json=bad), 422, "validation_error")
    huge = {"params": {**bad["params"], "amount_minor": 10**30}}
    _assert_error(client.patch(f"/rules/{rule_id}", json=huge), 422, "validation_error")
    item_id = detail["uncompilable"][0]["id"]
    bad_item = {"categories": ["spa"], "effect": "informational"}
    _assert_error(
        client.patch(f"/uncompilable/{item_id}", json=bad_item), 422, "validation_error"
    )


def test_active_version_is_immutable(client, active):
    detail = client.get(f"/policies/{active}/versions/1").json()
    rule_id = detail["rules"][0]["id"]
    _assert_error(
        client.patch(f"/rules/{rule_id}", json={"status": "rejected"}),
        409,
        "version_immutable",
    )
    _assert_error(
        client.post(
            f"/policies/{active}/versions/1/rules",
            json={
                "params": {"type": "prohibited_category", "category": "meals"},
                "clause": "Meals are capped at USD 50 per expense.",
            },
        ),
        409,
        "version_immutable",
    )
    _assert_error(
        client.post(f"/policies/{active}/versions/1/compile"), 409, "version_immutable"
    )


def test_compile_in_progress_is_a_conflict(client, db, draft):
    policy_id, _ = draft
    with transaction(db):
        policy_store.set_version_status(db, policy_id, 1, VersionStatus.COMPILING)
    _assert_error(
        client.post(f"/policies/{policy_id}/versions/1/compile"),
        409,
        "compile_in_progress",
    )


def test_compile_failure_leaves_nothing(tmp_path, monkeypatch):
    # The default compiler is chosen by the environment: force the mock, which
    # only knows the sample policies.
    monkeypatch.setenv("COVERED_PROVIDER", "mock")
    db = open_database(tmp_path / "default.db")
    add_users(db)
    db.close()
    app = create_app(tmp_path / "default.db")
    with TestClient(app, headers=bearer("fede")) as client:
        policy = client.post("/policies", json={"name": "Sales"}).json()
        client.post(f"/policies/{policy['id']}/versions", json={"text": "Some text."})
        response = client.post(f"/policies/{policy['id']}/versions/1/compile")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "compile_failed"
    assert body["compile_error"] == "mock mode only supports the sample policies"
    assert body["rules"] == [] and body["uncompilable"] == []


# Expenses


def test_check_returns_a_decision_and_stores_nothing(client, active):
    response = client.post("/expenses/check", json=TAXI, headers=ANA)
    assert response.status_code == 200
    decision = response.json()
    assert decision["outcome"] == "approved"
    assert decision["expense_id"] is None
    assert client.get("/expenses", params={"employee_id": "ana"}).json() == []


def test_submit_with_huge_amount_is_a_validation_error(client, active):
    response = _submit(client, "key-huge", amount_minor=10**30)
    _assert_error(response, 422, "validation_error")


def test_submit_requires_idempotency_key(client, active):
    _assert_error(
        client.post("/expenses", json=TAXI, headers=ANA), 422, "validation_error"
    )


def test_idempotent_replay_returns_same_status_and_body(client, active):
    first = _submit(client, "key-1")
    replay = _submit(client, "key-1")
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.json()["expense"]["amount_minor"] == 6000
    assert len(client.get("/expenses", params={"employee_id": "ana"}).json()) == 1


def test_idempotency_key_reused_with_different_body(client, active):
    _submit(client, "key-1")
    _assert_error(
        _submit(client, "key-1", amount_minor=6100), 409, "idempotency_key_reused"
    )


def test_decisions_cite_rule_and_clause(client, active):
    body = _submit(client, "key-1", amount_minor=9000).json()
    assert body["expense"]["status"] == "pending"
    reason = body["decision"]["reasons"][0]
    assert reason["clause"] == "Ground transport above USD 80 requires pre-approval."
    assert reason["rule_id"] is not None
    assert body["decision"]["policy_version"] == 1


def test_resolve_transitions(client, active):
    pending = _submit(client, "key-1", amount_minor=9000).json()["expense"]["id"]
    approved = _submit(client, "key-2").json()["expense"]["id"]

    resolved = client.post(
        f"/expenses/{pending}/resolve", json={"resolution": "approved"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["expense"]["status"] == "approved"
    assert resolved.json()["expense"]["resolved_by"] == "fede"

    for expense_id in (pending, approved):
        _assert_error(
            client.post(
                f"/expenses/{expense_id}/resolve", json={"resolution": "rejected"}
            ),
            409,
            "invalid_transition",
        )
    _assert_error(
        client.post("/expenses/999/resolve", json={"resolution": "approved"}),
        404,
        "not_found",
    )
    _assert_error(
        client.post(f"/expenses/{pending}/resolve", json={"resolution": "pending"}),
        422,
        "validation_error",
    )


def test_list_expenses_filters(client, active):
    _submit(client, "key-1", amount_minor=9000)
    _submit(client, "key-2")
    pending = client.get("/expenses", params={"status": "pending"}).json()
    assert [item["expense"]["amount_minor"] for item in pending] == [9000]
    assert pending[0]["decision"]["outcome"] == "needs_approval"


def test_no_active_policy_is_a_conflict(client, db, draft):
    policy_id, _ = draft
    employees.create_employee(db, "bruno", "Bruno", policy_id, token="demo-bruno")
    payload = {**TAXI, "employee_id": "bruno"}
    bruno = bearer("bruno")
    _assert_error(
        client.post("/expenses/check", json=payload, headers=bruno),
        409,
        "no_active_policy",
    )
    _assert_error(
        client.post(
            "/expenses", json=payload, headers={"Idempotency-Key": "k", **bruno}
        ),
        409,
        "no_active_policy",
    )

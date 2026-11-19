"""End to end on the seeded demo: the scenarios the demo walks through."""

import json
import logging

from covered.services.seed import reset_database, seed

WEDNESDAY_NOON = "2026-11-18T12:00:00-03:00"
SUNDAY_LATE = "2026-11-22T23:30:00-03:00"


def expense(employee, amount_minor, category, occurred_at=WEDNESDAY_NOON, **extra):
    return {
        "employee_id": employee,
        "amount_minor": amount_minor,
        "category": category,
        "occurred_at": occurred_at,
        **extra,
    }


def as_employee(kwargs) -> dict[str, str]:
    """Check/submit act as the expense's own employee (SPEC §12a)."""
    return {"Authorization": f"Bearer demo-{kwargs['employee']}"}


def check(client, **kwargs):
    response = client.post(
        "/expenses/check", json=expense(**kwargs), headers=as_employee(kwargs)
    )
    assert response.status_code == 200, response.json()
    return response.json()


def submit(client, key, **kwargs):
    response = client.post(
        "/expenses",
        json=expense(**kwargs),
        headers={"Idempotency-Key": key, **as_employee(kwargs)},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def test_seed_creates_two_active_policies_and_six_demo_users(client):
    policies = client.get("/policies").json()
    assert {p["name"]: p["active_version"] for p in policies} == {
        "Sales": 1,
        "Engineering": 1,
    }
    staff = {
        e["id"]: (e["policy_id"], e["manager_id"], e["roles"])
        for e in client.get("/employees").json()
    }
    assert staff == {
        "ana": (1, "bruno", ["employee"]),
        "bruno": (1, "fede", ["employee", "manager"]),
        "carla": (2, "diego", ["employee"]),
        "diego": (2, "fede", ["employee", "manager"]),
        "fede": (2, None, ["employee", "finance"]),
        "gabi": (2, None, ["employee", "finance"]),
    }


def test_seed_is_repeatable(seeded_db):
    conn = reset_database(seeded_db)
    details = seed(conn)
    conn.close()
    assert [d.status for d in details] == ["active", "active"]


def test_meal_within_limits_is_approved_with_warnings(client):
    decision = check(client, employee="ana", amount_minor=5000, category="meals")
    assert decision["outcome"] == "approved"
    assert decision["reasons"] == []
    clauses = [w["clause"] for w in decision["warnings"]]
    assert "Client meals require a reasonable business justification." in clauses


def test_lodging_above_threshold_needs_approval(client):
    decision = check(client, employee="ana", amount_minor=12000, category="lodging")
    assert decision["outcome"] == "needs_approval"
    assert [r["outcome"] for r in decision["reasons"]] == ["needs_approval"]
    assert "pre-approval" in decision["reasons"][0]["clause"]


def test_late_sunday_expensive_meal_is_rejected_with_every_reason(client):
    decision = check(
        client,
        employee="ana",
        amount_minor=9550,
        category="meals",
        occurred_at=SUNDAY_LATE,
    )
    assert decision["outcome"] == "rejected"
    outcomes = sorted(r["outcome"] for r in decision["reasons"])
    assert outcomes == ["needs_approval", "rejected", "rejected"]
    assert all(r["clause"] for r in decision["reasons"])


def test_engineering_prohibits_entertainment(client):
    decision = check(
        client, employee="carla", amount_minor=1000, category="entertainment"
    )
    assert decision["outcome"] == "rejected"


def test_uncovered_category_needs_approval(client):
    decision = check(client, employee="bruno", amount_minor=1000, category="software")
    assert decision["outcome"] == "needs_approval"
    assert decision["reasons"][-1]["source"] == "uncovered_category"


def test_period_limit_worked_example(client):
    """SPEC §4.3 on the seeded Sales policy (USD 200/month, threshold USD 80)."""
    taxi = {"employee": "ana", "category": "ground_transport"}
    first = submit(client, "taxi-1", amount_minor=6000, **taxi)
    assert first["decision"]["outcome"] == "approved"
    second = submit(client, "taxi-2", amount_minor=9000, **taxi)
    assert second["decision"]["outcome"] == "needs_approval"

    third = check(client, amount_minor=7000, **taxi)
    assert third["outcome"] == "needs_approval"
    [reason] = third["reasons"]
    assert "USD 90.00" in reason["message"]


def test_every_decision_is_logged_as_json(client, caplog):
    with caplog.at_level(logging.INFO, logger="covered"):
        check(client, employee="ana", amount_minor=9550, category="meals")
    events = [json.loads(r.getMessage()) for r in caplog.records]
    [decision] = [e for e in events if e["event"] == "expense_decision"]
    assert decision["employee_id"] == "ana"
    assert decision["policy_version"] == 1
    assert decision["outcome"] == "rejected"
    assert decision["rule_ids"]

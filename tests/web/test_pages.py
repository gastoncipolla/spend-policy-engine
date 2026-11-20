"""Server-rendered pages (SPEC §8)."""

import json
import logging
from pathlib import Path

from covered.web.highlight import highlight_clauses

SALES_TEXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "policies" / "sales.md"
).read_text(encoding="utf-8")


def act_as(client, user_id, page="/"):
    """Pick a demo user in the "act as" selector (sets the cookie)."""
    return client.post("/act-as", data={"user_id": user_id, "next": page})


def employee_form(**overrides):
    form = {
        "amount": "95.50",
        "category": "meals",
        "occurred_at": "2026-11-22T23:30",  # Sunday, company time
        "action": "check",
        "idempotency_key": "page-key-1",
    }
    return {**form, **overrides}


def test_home_asks_who_you_are_then_shows_what_you_may_see(client):
    anonymous = client.get("/")
    assert anonymous.status_code == 200
    assert "mock (sample policies only)" in anonymous.text
    assert 'action="/act-as"' in anonymous.text and "Sales" not in anonymous.text

    finance = act_as(client, "fede")
    assert 'href="/employee"' in finance.text and 'href="/finance"' in finance.text
    assert "Sales" in finance.text and "Engineering" in finance.text

    employee = act_as(client, "ana")
    assert 'href="/finance"' not in employee.text
    assert "Sales" in employee.text and "Engineering" not in employee.text


def test_act_as_unknown_user_clears_the_cookie(client):
    act_as(client, "ana")
    page = act_as(client, "nobody", "/employee")
    assert "Choose who you are" in page.text


def test_employee_page_is_for_the_current_user(client):
    act_as(client, "bruno")
    page = client.get("/employee")
    assert page.status_code == 200
    assert "Expense for Bruno" in page.text
    assert "Will this be covered?" in page.text
    assert "Team pending" in page.text
    act_as(client, "ana")
    assert "Team pending" not in client.get("/employee").text


def test_employee_check_shows_outcome_and_quoted_clauses(client):
    act_as(client, "ana")
    page = client.post("/employee", data=employee_form())
    assert page.status_code == 200
    assert "badge big rejected" in page.text
    assert "“Meals are reimbursed up to USD 80.00 per expense.”" in page.text
    assert "Check only: nothing was stored." in page.text
    assert client.get("/expenses").json() == []


def test_employee_submit_stores_once_even_if_reposted(client):
    act_as(client, "ana")
    form = employee_form(
        action="submit", amount="40.00", occurred_at="2026-11-18T12:00"
    )
    first = client.post("/employee", data=form)
    again = client.post("/employee", data=form)
    assert "Submitted as expense #1." in first.text
    assert "Submitted as expense #1." in again.text
    assert len(client.get("/expenses").json()) == 1


def test_employee_invalid_amount_shows_error(client):
    act_as(client, "ana")
    page = client.post("/employee", data=employee_form(amount="1.234"))
    assert page.status_code == 200
    assert "more than 2 decimal places" in page.text


def test_employee_post_without_a_user_stores_nothing(client):
    page = client.post("/employee", data=employee_form(action="submit"))
    assert "Choose who you are" in page.text
    assert client.get("/expenses").json() == []


def test_finance_view_requires_finance(client):
    assert client.get("/finance").status_code == 403
    act_as(client, "bruno")
    page = client.get("/finance")
    assert page.status_code == 403 and "for finance" in page.text
    refused = client.post("/finance/activate", data={"policy_id": 1, "version": 1})
    assert "only finance can activate" in refused.text


def test_finance_shows_policy_text_next_to_rules(client):
    act_as(client, "fede")
    page = client.get("/finance?policy_id=1")
    assert page.status_code == 200
    assert '<mark id="clause-R1">' in page.text
    assert "Meals: at most USD 80.00 per expense" in page.text
    assert "Uncovered categories" in page.text


def test_finance_review_flow_new_version_compile_approve_activate(client, caplog):
    act_as(client, "fede")
    created = client.post(
        "/finance/versions", data={"policy_id": 1, "text": SALES_TEXT}
    )
    assert created.status_code == 200  # followed the 303 back to /finance
    assert "Draft created" in created.text

    with caplog.at_level(logging.INFO, logger="covered"):
        compiled = client.post("/finance/compile", data={"policy_id": 1, "version": 2})
    assert "Compiled: review the proposed rules." in compiled.text
    events = [json.loads(r.getMessage()) for r in caplog.records]
    [event] = [e for e in events if e["event"] == "policy_compiled"]
    assert event["provider"] == "mock" and event["outcome"] == "ok"
    assert "prompt_version" in event and "cost_usd" in event

    blocked = client.post("/finance/activate", data={"policy_id": 1, "version": 2})
    assert "proposed" in blocked.text  # activation blocked while rules are proposed

    detail = client.get("/policies/1/versions/2").json()
    for rule in detail["rules"]:
        data = {"status": "approved", "policy_id": 1, "version": 2}
        client.post(f"/finance/rules/{rule['id']}", data=data)
    for item in detail["uncompilable"]:
        data = {
            "categories": item["categories"],
            "effect": item["effect"],
            "policy_id": 1,
            "version": 2,
        }
        client.post(f"/finance/uncompilable/{item['id']}", data=data)
    activated = client.post("/finance/activate", data={"policy_id": 1, "version": 2})
    assert "Version 2 is now active." in activated.text
    statuses = {
        v["version"]: v["status"] for v in client.get("/policies").json()[0]["versions"]
    }
    assert statuses == {1: "retired", 2: "active"}


def test_finance_resolves_pending_expense(client):
    act_as(client, "ana")
    client.post(
        "/employee",
        data=employee_form(
            action="submit",
            amount="120.00",
            category="lodging",
            occurred_at="2026-11-18T12:00",
        ),
    )
    act_as(client, "fede")
    finance = client.get("/finance")
    assert "Pending expenses" in finance.text and "USD 120.00" in finance.text
    resolved = client.post(
        "/finance/expenses/1/resolve",
        data={"resolution": "approved", "policy_id": 1, "version": 1},
    )
    assert "Expense #1 approved." in resolved.text
    again = client.post(
        "/finance/expenses/1/resolve",
        data={"resolution": "rejected", "policy_id": 1, "version": 1},
    )
    assert 'class="alert error"' in again.text
    assert client.get("/expenses/1").json()["expense"]["resolved_by"] == "fede"


def test_manager_resolves_team_pending_but_not_their_own(client):
    pending = employee_form(
        action="submit",
        amount="120.00",
        category="lodging",
        occurred_at="2026-11-18T12:00",
    )
    act_as(client, "ana")
    client.post("/employee", data=pending)  # expense #1
    act_as(client, "bruno")
    client.post("/employee", data={**pending, "idempotency_key": "bruno-1"})  # #2

    page = client.get("/employee")
    assert 'action="/employee/expenses/1/resolve"' in page.text
    assert 'action="/employee/expenses/2/resolve"' not in page.text

    own = client.post("/employee/expenses/2/resolve", data={"resolution": "approved"})
    assert "separation of duties" in own.text
    resolved = client.post(
        "/employee/expenses/1/resolve", data={"resolution": "rejected"}
    )
    assert "Expense #1 rejected." in resolved.text
    assert client.get("/expenses/1").json()["expense"]["resolved_by"] == "bruno"

    act_as(client, "fede")
    finance = client.get("/finance")
    assert 'action="/finance/expenses/2/resolve"' in finance.text


def test_highlight_escapes_html_and_marks_clauses():
    html = highlight_clauses("<b>Meals</b> up to USD 80.", {"up to USD 80.": "R1"})
    assert str(html) == (
        '&lt;b&gt;Meals&lt;/b&gt; <mark id="clause-R1">up to USD 80.<sup>R1</sup></mark>'
    )


def test_identity_bar_says_who_you_are_and_what_you_can_do(client):
    anonymous = client.get("/employee")
    assert "No demo user chosen." in anonymous.text

    page = act_as(client, "bruno", "/employee")
    assert '<strong class="who-name">Bruno</strong>' in page.text
    assert '<span class="role role-manager">manager</span>' in page.text
    assert "approve or reject the team&#39;s pending expenses (never own)" in page.text
    assert '<a href="/employee" aria-current="page">' in page.text


def test_home_lists_demo_users_with_one_click_act_as(client):
    page = client.get("/")
    assert "Demo users" in page.text
    assert "Act as Gabi" in page.text and "reports to diego" in page.text
    act_as(client, "fede")
    assert '<span class="badge active">You</span>' in client.get("/").text


def test_decision_explains_outcome_and_highlights_cited_clauses(client):
    act_as(client, "ana")
    page = client.post("/employee", data=employee_form())
    assert "Not reimbursable under this policy." in page.text
    assert (
        '<span class="cite">Rule R1 cites the policy:</span> '
        "<mark>“Meals are reimbursed up to USD 80.00 per expense.”</mark>"
    ) in page.text
    assert "Clause U1 cites the policy:" in page.text  # informational note
    assert '<span class="badge note">Note</span>' in page.text


def test_history_shows_status_in_words(client):
    act_as(client, "ana")
    form = employee_form(
        action="submit",
        amount="120.00",
        category="lodging",
        occurred_at="2026-11-18T12:00",
    )
    client.post("/employee", data=form)
    page = client.get("/employee")
    assert '<span class="badge pending">Pending approval</span>' in page.text
    assert 'data-label="Status"' in page.text  # stacks into cards on phones


def test_empty_states_explain_what_to_do(client):
    act_as(client, "bruno")
    page = client.get("/employee")
    assert "No submitted expenses yet." in page.text
    assert "Nothing pending." in page.text


def test_finance_separates_uncompilable_clauses_and_links_rules_to_text(client):
    act_as(client, "fede")
    page = client.get("/finance?policy_id=1")
    assert '<a class="label" href="#clause-R1"' in page.text
    assert '<div class="card uncompilable">' in page.text
    assert "Why not a rule:" in page.text
    assert "informational (note only)" in page.text
    assert '<label for="policy-pick">Policy</label>' in page.text

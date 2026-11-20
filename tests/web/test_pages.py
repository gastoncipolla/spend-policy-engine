"""Server-rendered pages (SPEC §8)."""

import json
import logging
from pathlib import Path

from covered.web.highlight import highlight_clauses

SALES_TEXT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "policies" / "sales.md"
).read_text(encoding="utf-8")


def act_as(client, user_id, page="/"):
    """Sign in as a demo user from the demo panel (sets the cookie)."""
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


NAV = {
    "/employee": 'href="/employee"',
    "/team": 'href="/team"',
    "/finance": 'href="/finance"',
}


def nav_links(page):
    header = page.text.split("<main>")[0]
    return {path for path, link in NAV.items() if link in header}


def test_landing_without_a_user_is_the_demo_panel(client):
    landing = client.get("/", follow_redirects=False)
    assert landing.status_code == 303 and landing.headers["location"] == "/demo"
    panel = client.get("/demo")
    assert "Choose a user to sign in as" in panel.text
    assert "<strong>mock</strong> (sample policies only)" in panel.text
    assert "Sign in as Gabi" in panel.text and "reports to Diego" in panel.text
    assert "Review rules, activate policies" in panel.text  # what each role can do
    assert nav_links(panel) == set()


def test_landing_with_a_user_redirects_home(client):
    for user in ("ana", "bruno", "fede"):
        act_as(client, user)
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 303 and home.headers["location"] == "/employee"


def test_signing_in_lands_on_the_users_home(client):
    response = client.post(
        "/act-as", data={"user_id": "fede", "next": "/"}, follow_redirects=False
    )
    assert response.headers["location"] == "/employee"


def test_switching_user_never_lands_on_a_forbidden_page(client):
    act_as(client, "fede")
    response = client.post(
        "/act-as", data={"user_id": "ana", "next": "/finance"}, follow_redirects=False
    )
    assert response.headers["location"] == "/employee"
    response = client.post(
        "/act-as", data={"user_id": "bruno", "next": "/team"}, follow_redirects=False
    )
    assert response.headers["location"] == "/team"


def test_nav_shows_only_pages_the_user_may_open(client):
    expected = {
        "ana": {"/employee"},
        "carla": {"/employee"},
        "bruno": {"/employee", "/team"},
        "gabi": {"/employee", "/finance"},
        "fede": {"/employee", "/team", "/finance"},
    }
    for user, paths in expected.items():
        page = act_as(client, user)
        assert nav_links(page) == paths, user
        for path in NAV:
            status = client.get(path).status_code
            assert (status == 200) == (path in paths), (user, path, status)


def test_nav_counts_what_is_waiting_for_you(client):
    submit_pending_as(client, "ana")
    page = act_as(client, "bruno")
    assert 'aria-label="1 waiting for you">1</span>' in page.text
    assert "1 expense from your team is waiting for your decision." in page.text
    fede = act_as(client, "fede")  # finance sees it; it is not his team's
    assert '<a href="/team" ><span' not in fede.text
    assert 'Finance <span class="count attention"' in fede.text


def test_product_pages_have_no_act_as_select_but_a_user_menu(client):
    page = act_as(client, "bruno")
    assert '<select id="act-as"' not in page.text
    assert '<details class="user-menu">' in page.text
    assert '<span class="user-name">Bruno</span>' in page.text
    assert "Demo mode" in page.text and 'href="/demo">Switch user</a>' in page.text


def test_sign_out_clears_the_user(client):
    act_as(client, "ana")
    page = act_as(client, "")
    assert "Choose a user to sign in as" in page.text
    assert client.get("/", follow_redirects=False).headers["location"] == "/demo"


def test_act_as_unknown_user_clears_the_cookie(client):
    act_as(client, "ana")
    page = act_as(client, "nobody", "/employee")
    assert "Choose a user to sign in as" in page.text
    assert client.get("/employee", follow_redirects=False).status_code == 303


def test_employee_page_is_for_the_current_user(client):
    act_as(client, "bruno")
    page = client.get("/employee")
    assert page.status_code == 200
    assert "<h1>My expenses</h1>" in page.text
    assert "Expense for Bruno" in page.text
    assert "Will this be covered?" in page.text
    assert "Your policy: <strong>Sales</strong>" in page.text


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


def submit_pending_as(client, user_id):
    """`user_id` submits a lodging expense that needs approval."""
    act_as(client, user_id)
    form = employee_form(
        action="submit",
        amount="120.00",
        category="lodging",
        occurred_at="2026-11-18T12:00",
        idempotency_key=f"pending-{user_id}",
    )
    client.post("/employee", data=form)


def test_team_page_is_for_managers(client):
    act_as(client, "ana")
    denied = client.get("/team")
    assert denied.status_code == 403 and "for managers" in denied.text
    act_as(client, "bruno")
    page = client.get("/team")
    assert "<h1>Team approvals</h1>" in page.text
    assert "Your team:\n  <strong>Ana</strong>" in page.text
    assert "Nothing waiting for you." in page.text


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
    assert "Expenses pending approval" in finance.text
    assert "USD 120.00" in finance.text
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

    page = client.get("/team")
    assert 'action="/employee/expenses/1/resolve"' in page.text
    assert 'action="/employee/expenses/2/resolve"' not in page.text

    assert "Your own expense" not in page.text  # only the team's, never your own
    own = client.post("/employee/expenses/2/resolve", data={"resolution": "approved"})
    assert "separation of duties" in own.text
    resolved = client.post(
        "/employee/expenses/1/resolve", data={"resolution": "rejected"}
    )
    assert "Expense #1 rejected." in resolved.text
    assert "<h1>Team approvals</h1>" in resolved.text
    assert client.get("/expenses/1").json()["expense"]["resolved_by"] == "bruno"

    act_as(client, "fede")
    finance = client.get("/finance")
    assert 'action="/finance/expenses/2/resolve"' in finance.text


def test_highlight_escapes_html_and_marks_clauses():
    html = highlight_clauses("<b>Meals</b> up to USD 80.", {"up to USD 80.": "R1"})
    assert str(html) == (
        '&lt;b&gt;Meals&lt;/b&gt; <mark id="clause-R1">up to USD 80.<sup>R1</sup></mark>'
    )


def test_user_menu_says_who_you_are_and_what_you_can_do(client):
    page = act_as(client, "bruno", "/employee")
    assert "signed in as <strong>Bruno</strong>" in page.text
    assert '<span class="role role-manager">manager</span>' in page.text
    assert "Approve or reject the team&#39;s pending expenses (never own)" in page.text
    assert '<a href="/employee" aria-current="page">' in page.text


def test_demo_panel_marks_the_current_user(client):
    act_as(client, "fede")
    page = client.get("/demo")
    assert '<span class="badge active">Signed in</span>' in page.text
    assert "Continue as Fede" in page.text and "Sign in as Ana" in page.text


def test_decision_explains_outcome_and_highlights_cited_clauses(client):
    act_as(client, "ana")
    page = client.post("/employee", data=employee_form())
    assert "Not reimbursable under this policy." in page.text
    assert (
        '<span class="cite">Rule R1 cites the policy:</span> '
        "<mark>“Meals are reimbursed up to USD 80.00 per expense.”</mark>"
    ) in page.text


def test_informational_notes_are_collapsed_below_the_reasons(client):
    act_as(client, "ana")
    page = client.post("/employee", data=employee_form()).text
    # Notes never change the outcome: one closed <details>, after the reasons.
    assert "<summary>Policy notes (2)</summary>" in page
    assert (
        '<details class="notes">' in page and '<details class="notes" open' not in page
    )
    assert "“Personal expenses are not reimbursable.”" in page
    assert page.index("Rule R1 cites the policy:") < page.index("Policy notes")
    assert "Clause U1 cites the policy:" not in page
    assert "Keep this policy clause in mind" not in page


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
    assert "No submitted expenses yet." in client.get("/employee").text
    assert "Nothing waiting for you." in client.get("/team").text
    act_as(client, "fede")
    assert "Nothing pending." in client.get("/finance").text


def test_finance_separates_uncompilable_clauses_and_links_rules_to_text(client):
    act_as(client, "fede")
    page = client.get("/finance?policy_id=1")
    assert '<a class="label" href="#clause-R1"' in page.text
    assert '<div class="card uncompilable">' in page.text
    assert "Why not a rule:" in page.text
    assert "informational (note only)" in page.text
    assert '<label for="policy-pick">Policy</label>' in page.text

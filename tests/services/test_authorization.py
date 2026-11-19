"""SPEC §12a in the service layer: the permission matrix on the seeded demo users.

ana (employee, manager bruno), bruno (employee + manager, manager fede),
carla (employee, manager diego), diego (employee + manager, manager fede),
fede (employee + finance, no manager).
"""

from datetime import datetime

import pytest
from service_builders import TZ

from covered.domain import (
    Category,
    ExpenseInput,
    MaxAmountParams,
    UncompilableEffect,
)
from covered.domain.errors import ForbiddenError, NotFoundError, UnauthenticatedError
from covered.services import employees, expenses, policies
from covered.services.compilation import compile_version
from covered.services.seed import reset_database, seed
from covered.store.records import ExpenseStatus, Role, RuleStatus

SALES, ENGINEERING = 1, 2
APPROVED, REJECTED = ExpenseStatus.APPROVED, ExpenseStatus.REJECTED


@pytest.fixture
def demo(tmp_path):
    conn = reset_database(str(tmp_path / "demo.db"))
    seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def users(demo):
    return {
        user_id: employees.act_as(demo, user_id)
        for user_id in ("ana", "bruno", "carla", "diego", "fede")
    }


@pytest.fixture
def pending(demo, users):
    """One pending expense (airfare without review) per user: {user id: expense id}."""
    ids = {}
    for user_id, actor in users.items():
        result = expenses.submit_expense(demo, actor, _airfare(user_id), f"k-{user_id}")
        assert result.body["expense"]["status"] == "pending"
        ids[user_id] = result.body["expense"]["id"]
    return ids


def _airfare(employee_id: str) -> ExpenseInput:
    return ExpenseInput(
        employee_id=employee_id,
        amount_minor=30000,
        category=Category.AIRFARE,
        occurred_at=datetime(2026, 11, 18, 10, 0, tzinfo=TZ),
    )


# Identity


def test_authenticate_by_demo_token(demo):
    assert employees.authenticate(demo, "demo-ana").id == "ana"
    for token in (None, "", "demo-nobody"):
        with pytest.raises(UnauthenticatedError):
            employees.authenticate(demo, token)


# List employees: self / self + team / all


@pytest.mark.parametrize(
    ("user", "visible"),
    [
        ("ana", ["ana"]),
        ("bruno", ["ana", "bruno"]),
        ("diego", ["carla", "diego"]),
        ("fede", ["ana", "bruno", "carla", "diego", "fede"]),
    ],
)
def test_list_employees(demo, users, user, visible):
    assert [e.id for e in employees.list_employees(demo, users[user])] == visible


# Check / submit: own only, finance included


@pytest.mark.parametrize("user", ["ana", "bruno", "fede"])
def test_check_and_submit_only_for_yourself(demo, users, user):
    other = "carla"
    with pytest.raises(ForbiddenError):
        expenses.check_expense(demo, users[user], _airfare(other))
    with pytest.raises(ForbiddenError):
        expenses.submit_expense(demo, users[user], _airfare(other), "k")
    assert expenses.list_expenses(demo, users["fede"]) == []


# List / get expenses: own / own + team / all


@pytest.mark.parametrize(
    ("user", "visible"),
    [
        ("ana", {"ana"}),
        ("carla", {"carla"}),
        ("bruno", {"ana", "bruno"}),
        ("diego", {"carla", "diego"}),
        ("fede", {"ana", "bruno", "carla", "diego", "fede"}),
    ],
)
def test_list_expenses_is_filtered(demo, users, pending, user, visible):
    listed = expenses.list_expenses(demo, users[user])
    assert {item.expense.employee_id for item in listed} == visible


def test_filtering_by_a_hidden_employee_returns_nothing(demo, users, pending):
    assert expenses.list_expenses(demo, users["ana"], employee_id="carla") == []
    assert expenses.list_expenses(demo, users["bruno"], employee_id="carla") == []
    team = expenses.list_expenses(demo, users["bruno"], employee_id="ana")
    assert [item.expense.id for item in team] == [pending["ana"]]


def test_bola_hidden_expense_is_not_found(demo, users, pending):
    """Ana asks for Carla's expense: 404, exactly like an id that does not exist."""
    for user, owner in [("ana", "carla"), ("ana", "bruno"), ("bruno", "carla")]:
        with pytest.raises(NotFoundError) as hidden:
            expenses.get_expense(demo, users[user], pending[owner])
        with pytest.raises(NotFoundError) as missing:
            expenses.get_expense(demo, users[user], 999)
        assert hidden.value.message.replace(str(pending[owner]), "N") == (
            missing.value.message.replace("999", "N")
        )


def test_get_visible_expenses(demo, users, pending):
    assert expenses.get_expense(demo, users["ana"], pending["ana"]).expense.id
    assert expenses.get_expense(demo, users["bruno"], pending["ana"]).expense.id
    assert expenses.get_expense(demo, users["fede"], pending["carla"]).expense.id


# Resolve: never own; managers their team; finance anyone


@pytest.mark.parametrize("user", ["ana", "bruno", "fede"])
def test_nobody_resolves_their_own_expense(demo, users, pending, user):
    with pytest.raises(ForbiddenError, match="separation of duties"):
        expenses.resolve_expense(demo, users[user], pending[user], APPROVED)
    assert expenses.get_expense(demo, users["fede"], pending[user]).expense.status == (
        ExpenseStatus.PENDING
    )


@pytest.mark.parametrize(
    ("user", "owner"),
    [("ana", "carla"), ("ana", "bruno"), ("bruno", "carla"), ("diego", "bruno")],
)
def test_resolving_an_expense_you_cannot_see_is_not_found(
    demo, users, pending, user, owner
):
    with pytest.raises(NotFoundError):
        expenses.resolve_expense(demo, users[user], pending[owner], APPROVED)


def test_manager_resolves_team_member_and_audit_is_recorded(demo, users, pending):
    resolved = expenses.resolve_expense(demo, users["bruno"], pending["ana"], REJECTED)
    assert resolved.expense.status is REJECTED
    assert resolved.expense.resolved_by == "bruno"
    assert resolved.expense.resolved_at is not None


def test_managers_own_pending_is_resolved_by_their_manager_or_finance(
    demo, users, pending
):
    # hugo manages nobody yet and reports to diego, a manager who is not finance.
    employees.create_employee(
        demo,
        "hugo",
        "Hugo",
        SALES,
        roles=[Role.EMPLOYEE, Role.MANAGER],
        manager_id="diego",
    )
    hugo = employees.act_as(demo, "hugo")
    own = expenses.submit_expense(demo, hugo, _airfare("hugo"), "k-hugo")
    own_id = own.body["expense"]["id"]

    with pytest.raises(ForbiddenError):
        expenses.resolve_expense(demo, hugo, own_id, APPROVED)
    by_manager = expenses.resolve_expense(demo, users["diego"], own_id, APPROVED)
    assert by_manager.expense.resolved_by == "diego"

    # bruno's manager is fede, who is also finance.
    by_finance = expenses.resolve_expense(
        demo, users["fede"], pending["bruno"], APPROVED
    )
    assert by_finance.expense.resolved_by == "fede"


def test_finance_resolves_anyone_else(demo, users, pending):
    resolved = expenses.resolve_expense(demo, users["fede"], pending["carla"], APPROVED)
    assert resolved.expense.resolved_by == "fede"


# Policies: read own (active version only) / all; administration finance only


def test_non_finance_reads_only_their_policy_active_version(demo, users):
    for user, own in [("ana", SALES), ("bruno", SALES), ("carla", ENGINEERING)]:
        listed = policies.list_policies(demo, users[user])
        assert [p.id for p in listed] == [own]
        assert policies.get_version_detail(demo, users[user], own, 1).version == 1
        other = ENGINEERING if own == SALES else SALES
        with pytest.raises(NotFoundError):
            policies.get_version_detail(demo, users[user], other, 1)


def test_drafts_are_visible_to_finance_only(demo, users):
    policies.create_version(demo, users["fede"], SALES, "Meals are capped at USD 1.")
    assert policies.get_version_detail(demo, users["fede"], SALES, 2).version == 2
    with pytest.raises(NotFoundError):
        policies.get_version_detail(demo, users["ana"], SALES, 2)
    (sales,) = policies.list_policies(demo, users["ana"])
    assert [v.version for v in sales.versions] == [1]
    assert len(policies.list_policies(demo, users["fede"])) == 2


@pytest.mark.parametrize("user", ["ana", "bruno", "diego"])
def test_policy_administration_is_finance_only(demo, users, user):
    actor = users[user]
    detail = policies.get_version_detail(demo, users["fede"], SALES, 1)
    rule, item = detail.rules[0], detail.uncompilable[0]
    text = "Meals are capped at USD 1."
    actions = [
        lambda: policies.create_policy(demo, actor, "Mine"),
        lambda: policies.create_version(demo, actor, SALES, text),
        lambda: compile_version(demo, actor, SALES, 1, lambda t: None),
        lambda: policies.update_rule(demo, actor, rule.id, status=RuleStatus.REJECTED),
        lambda: policies.add_manual_rule(
            demo,
            actor,
            SALES,
            1,
            MaxAmountParams(category="meals", amount_minor=1),
            "x",
        ),
        lambda: policies.classify_uncompilable(
            demo,
            actor,
            item.id,
            categories=["*"],
            effect=UncompilableEffect.INFORMATIONAL,
        ),
        lambda: policies.activate_version(demo, actor, SALES, 1),
    ]
    for action in actions:
        with pytest.raises(ForbiddenError, match="only finance"):
            action()


# Audit: every write records who and when


def test_seed_review_is_audited_as_finance(demo, users):
    detail = policies.get_version_detail(demo, users["fede"], SALES, 1)
    assert (detail.activated_by, bool(detail.activated_at)) == ("fede", True)
    assert {(r.reviewed_by, bool(r.reviewed_at)) for r in detail.rules} == {
        ("fede", True)
    }
    assert {(i.classified_by, bool(i.classified_at)) for i in detail.uncompilable} == {
        ("fede", True)
    }


def test_finance_writes_record_the_actor(demo, users):
    fede = users["fede"]
    policies.create_version(demo, fede, SALES, "Meals are capped at USD 1.")
    rule = policies.add_manual_rule(
        demo,
        fede,
        SALES,
        2,
        MaxAmountParams(category="meals", amount_minor=100),
        "Meals are capped at USD 1.",
    )
    assert rule.reviewed_by == "fede" and rule.reviewed_at is not None
    edited = policies.update_rule(demo, fede, rule.id, status=RuleStatus.REJECTED)
    assert edited.reviewed_by == "fede"

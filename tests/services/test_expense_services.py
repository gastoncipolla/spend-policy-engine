"""Expense use cases: check, submit (idempotency, concurrency), list, resolve."""

import threading

import pytest
from service_builders import FINANCE, POLICY_TEXT, expense

from covered.domain import Category, Outcome
from covered.domain.errors import (
    IdempotencyKeyReusedError,
    InvalidTransitionError,
    NoActivePolicyError,
    NotFoundError,
)
from covered.services import employees, expenses, policies
from covered.store.db import open_database
from covered.store.records import ExpenseStatus


def _submit(conn, actor, amount, key, **overrides):
    return expenses.submit_expense(conn, actor, expense(amount, **overrides), key)


def test_check_evaluates_without_storing(conn, sales, ana):
    decision = expenses.check_expense(conn, ana, expense(6000))
    assert decision.outcome is Outcome.APPROVED
    assert decision.expense_id is None
    assert (decision.policy_id, decision.policy_version) == (sales.id, 1)
    assert expenses.list_expenses(conn, ana, employee_id="ana") == []


def test_period_limit_worked_example(conn, sales, ana):
    """SPEC §4.3: taxi 60, 90 (pending via threshold), 70 → needs approval."""
    first = _submit(conn, ana, 6000, "k1").body
    second = _submit(conn, ana, 9000, "k2").body
    third = _submit(conn, ana, 7000, "k3").body

    assert first["expense"]["status"] == "approved"
    assert second["expense"]["status"] == "pending"
    assert third["decision"]["outcome"] == "needs_approval"
    assert "pending" in third["decision"]["reasons"][0]["message"]

    # A check counts stored approved/pending expenses, but stores nothing itself.
    assert expenses.check_expense(conn, ana, expense(15000)).outcome is Outcome.REJECTED


def test_submit_stores_expense_and_decision(conn, sales, ana):
    result = _submit(conn, ana, 6000, "k1")
    assert (result.status_code, result.replayed) == (201, False)
    listed = expenses.list_expenses(conn, ana, employee_id="ana")
    assert len(listed) == 1
    assert listed[0].decision.expense_id == listed[0].expense.id
    assert listed[0].decision.policy_version == 1


def test_idempotent_replay_returns_the_same_response(conn, sales, ana):
    first = _submit(conn, ana, 6000, "same-key")
    replay = _submit(conn, ana, 6000, "same-key")
    assert replay.replayed
    assert (replay.status_code, replay.body) == (first.status_code, first.body)
    assert len(expenses.list_expenses(conn, ana)) == 1


def test_idempotency_key_reused_with_different_body(conn, sales, ana):
    _submit(conn, ana, 6000, "same-key")
    with pytest.raises(IdempotencyKeyReusedError):
        _submit(conn, ana, 6100, "same-key")


def test_idempotency_keys_are_scoped_per_user(conn, sales, ana):
    """Two users sending the same key do not collide (SPEC §6)."""
    employees.create_employee(conn, "bea", "Bea", sales.id, token="t-bea")
    bea = employees.act_as(conn, "bea")
    for_ana = _submit(conn, ana, 6000, "shared-key")
    for_bea = _submit(conn, bea, 7000, "shared-key", employee_id="bea")
    assert not for_ana.replayed and not for_bea.replayed
    assert for_bea.body["expense"]["employee_id"] == "bea"
    assert for_bea.body["expense"]["id"] != for_ana.body["expense"]["id"]
    # Each user's key still replays its own response.
    assert _submit(conn, ana, 6000, "shared-key").body == for_ana.body
    replay = _submit(conn, bea, 7000, "shared-key", employee_id="bea")
    assert replay.replayed and replay.body == for_bea.body


def test_concurrent_submits_cannot_both_use_the_remaining_limit(db_path, ana):
    """Two 150 taxis with pre-approval against a 200 limit: one must be rejected."""
    outcomes = []
    barrier = threading.Barrier(2)

    def submit(key):
        own = open_database(db_path)
        barrier.wait()
        result = _submit(own, ana, 15000, key, pre_approval_id="PA-1")
        outcomes.append(result.body["decision"]["outcome"])
        own.close()

    threads = [threading.Thread(target=submit, args=(f"k{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["approved", "rejected"]


def test_no_active_policy_is_an_error_never_a_decision(conn):
    policy = policies.create_policy(conn, FINANCE, "Draft only")
    policies.create_version(conn, FINANCE, policy.id, POLICY_TEXT)
    employees.create_employee(conn, "bruno", "Bruno", policy.id)
    employees.create_employee(conn, "carla", "Carla", None)

    for employee_id in ("bruno", "carla"):
        actor = employees.act_as(conn, employee_id)
        with pytest.raises(NoActivePolicyError):
            expenses.check_expense(conn, actor, expense(100, employee_id=employee_id))
        with pytest.raises(NoActivePolicyError):
            _submit(conn, actor, 100, f"k-{employee_id}", employee_id=employee_id)
    assert expenses.list_expenses(conn, FINANCE) == []


def test_unknown_employee_is_not_found(conn, sales):
    nobody = FINANCE.model_copy(update={"id": "nobody"})
    with pytest.raises(NotFoundError):
        expenses.check_expense(conn, nobody, expense(100, employee_id="nobody"))


def test_resolve_pending_then_refuse_further_transitions(conn, sales, ana):
    pending = _submit(conn, ana, 9000, "k1").body["expense"]["id"]
    approved = _submit(conn, ana, 1000, "k2").body["expense"]["id"]

    resolved = expenses.resolve_expense(conn, FINANCE, pending, ExpenseStatus.APPROVED)
    assert resolved.expense.status is ExpenseStatus.APPROVED
    assert resolved.expense.resolved_by == "fede" and resolved.expense.resolved_at
    assert resolved.decision.outcome is Outcome.NEEDS_APPROVAL  # decision unchanged

    for expense_id in (pending, approved):
        with pytest.raises(InvalidTransitionError):
            expenses.resolve_expense(conn, FINANCE, expense_id, ExpenseStatus.REJECTED)
    with pytest.raises(NotFoundError):
        expenses.resolve_expense(conn, FINANCE, 999, ExpenseStatus.APPROVED)


def test_resolved_expenses_change_period_totals(conn, sales, ana):
    pending = _submit(conn, ana, 9000, "k1").body["expense"]["id"]
    expenses.resolve_expense(conn, FINANCE, pending, ExpenseStatus.REJECTED)
    # The rejected 90 no longer counts: 150 with pre-approval fits under 200.
    decision = expenses.check_expense(conn, ana, expense(15000, pre_approval_id="PA-1"))
    assert decision.outcome is Outcome.APPROVED


def test_list_filters_by_status(conn, sales, ana):
    _submit(conn, ana, 9000, "k1")
    _submit(conn, ana, 1000, "k2", category=Category.ALCOHOL)
    pending = expenses.list_expenses(conn, FINANCE, status=ExpenseStatus.PENDING)
    assert [item.expense.amount_minor for item in pending] == [9000]

"""Use cases: check, submit, list and resolve expenses (SPEC §6).

Submit evaluates and inserts inside one `BEGIN IMMEDIATE` transaction, so two
concurrent submits cannot both consume the same remaining period limit.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from covered.domain import Decision, ExpenseInput, Outcome, Period, PeriodHistory
from covered.domain.errors import (
    IdempotencyKeyReusedError,
    InvalidInputError,
    InvalidTransitionError,
    NotFoundError,
)
from covered.engine import evaluate, period_window
from covered.services.config import COMPANY_TZ, utc_now
from covered.services.events import log_event
from covered.services.policies import active_policy_for
from covered.store import employees as employee_store
from covered.store import expenses as expense_store
from covered.store import idempotency as idempotency_store
from covered.store.db import transaction
from covered.store.records import ExpenseStatus, StoredExpense

STATUS_BY_OUTCOME = {
    Outcome.APPROVED: ExpenseStatus.APPROVED,
    Outcome.NEEDS_APPROVAL: ExpenseStatus.PENDING,
    Outcome.REJECTED: ExpenseStatus.REJECTED,
}
SUBMIT_STATUS_CODE = 201


class ExpenseWithDecision(BaseModel):
    expense: StoredExpense
    decision: Decision


@dataclass(frozen=True)
class SubmitResult:
    """What `POST /expenses` returns; a replay returns the stored one verbatim."""

    status_code: int
    body: dict[str, Any]
    replayed: bool


def check_expense(
    conn: sqlite3.Connection, expense: ExpenseInput, *, now: datetime | None = None
) -> Decision:
    """Simulate: evaluate without storing anything or consuming any limit."""
    with transaction(conn):
        decision = _evaluate(conn, expense, now or utc_now())
    _log_decision(decision, kind="check")
    return decision


def submit_expense(
    conn: sqlite3.Connection,
    expense: ExpenseInput,
    idempotency_key: str,
    *,
    now: datetime | None = None,
) -> SubmitResult:
    key = idempotency_key.strip()
    if not key:
        raise InvalidInputError("the Idempotency-Key header must not be empty")
    request_hash = fingerprint(expense)
    with transaction(conn, immediate=True):
        record = idempotency_store.get_record(conn, key)
        if record is not None:
            if record.request_hash != request_hash:
                raise IdempotencyKeyReusedError(
                    "this Idempotency-Key was already used with a different request"
                )
            return SubmitResult(record.status_code, record.response, replayed=True)

        decision = _evaluate(conn, expense, now or utc_now())
        stored = expense_store.insert_expense(
            conn, expense, STATUS_BY_OUTCOME[decision.outcome]
        )
        decision = decision.model_copy(update={"expense_id": stored.id})
        expense_store.insert_decision(conn, decision)
        body = ExpenseWithDecision(expense=stored, decision=decision).model_dump(
            mode="json"
        )
        idempotency_store.insert_record(
            conn, key, request_hash, SUBMIT_STATUS_CODE, body
        )
    _log_decision(decision, kind="submit")
    return SubmitResult(SUBMIT_STATUS_CODE, body, replayed=False)


def list_expenses(
    conn: sqlite3.Connection,
    *,
    employee_id: str | None = None,
    status: ExpenseStatus | None = None,
) -> list[ExpenseWithDecision]:
    with transaction(conn):
        return [
            _with_decision(conn, expense)
            for expense in expense_store.list_expenses(
                conn, employee_id=employee_id, status=status
            )
        ]


def resolve_expense(
    conn: sqlite3.Connection, expense_id: int, resolution: ExpenseStatus
) -> ExpenseWithDecision:
    """pending → approved | rejected. Anything else is an invalid transition.

    The stored decision is left unchanged: it records what the policy said.
    """
    if resolution is ExpenseStatus.PENDING:
        raise InvalidInputError("resolution must be approved or rejected")
    with transaction(conn, immediate=True):
        expense = expense_store.get_expense(conn, expense_id)
        if expense is None:
            raise NotFoundError(f"expense {expense_id} not found")
        if expense.status is not ExpenseStatus.PENDING:
            raise InvalidTransitionError(
                f"expense {expense_id} is {expense.status}; only pending expenses can be resolved"
            )
        expense_store.set_expense_status(conn, expense_id, resolution)
        resolved = _with_decision(conn, expense_store.get_expense(conn, expense_id))
    log_event("expense_resolved", expense_id=expense_id, resolution=resolution)
    return resolved


def fingerprint(expense: ExpenseInput) -> str:
    """Hash of the validated request, so formatting differences do not matter."""
    canonical = json.dumps(expense.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _evaluate(
    conn: sqlite3.Connection, expense: ExpenseInput, evaluated_at: datetime
) -> Decision:
    employee = employee_store.get_employee(conn, expense.employee_id)
    if employee is None:
        raise NotFoundError(f"employee {expense.employee_id!r} not found")
    policy = active_policy_for(conn, employee)
    return evaluate(expense, policy, _history(conn, expense), COMPANY_TZ, evaluated_at)


def _history(conn: sqlite3.Connection, expense: ExpenseInput) -> PeriodHistory:
    totals = {}
    for period in Period:
        window = period_window(expense.occurred_at, period, COMPANY_TZ)
        totals[period.value] = expense_store.period_totals(
            conn, expense.employee_id, expense.category, window.start, window.end
        )
    return PeriodHistory(**totals)


def _with_decision(
    conn: sqlite3.Connection, expense: StoredExpense
) -> ExpenseWithDecision:
    return ExpenseWithDecision(
        expense=expense,
        decision=expense_store.get_decision_for_expense(conn, expense.id),
    )


def _log_decision(decision: Decision, *, kind: str) -> None:
    log_event(
        "expense_decision",
        kind=kind,
        employee_id=decision.employee_id,
        expense_id=decision.expense_id,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        outcome=decision.outcome,
        rule_ids=[r.rule_id for r in decision.reasons if r.rule_id is not None],
    )

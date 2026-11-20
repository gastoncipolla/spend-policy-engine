"""Repository: expenses, their decisions and period totals."""

import json
import sqlite3
from collections.abc import Collection
from datetime import datetime

from covered.domain import Category, Decision, ExpenseInput, PeriodTotals
from covered.store.db import to_utc_iso, utc_now_iso
from covered.store.records import ExpenseStatus, StoredExpense

_EXPENSE_COLUMNS = (
    "id, employee_id, amount_minor, currency, category, merchant, occurred_at,"
    " justification, pre_approval_id, status, created_at, resolved_by, resolved_at"
)


def insert_expense(
    conn: sqlite3.Connection, expense: ExpenseInput, status: ExpenseStatus
) -> StoredExpense:
    cursor = conn.execute(
        "INSERT INTO expenses (employee_id, amount_minor, currency, category, merchant,"
        " occurred_at, occurred_at_utc, justification, pre_approval_id, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            expense.employee_id,
            expense.amount_minor,
            expense.currency,
            expense.category,
            expense.merchant,
            expense.occurred_at.isoformat(),
            to_utc_iso(expense.occurred_at),
            expense.justification,
            expense.pre_approval_id,
            status,
            utc_now_iso(),
        ),
    )
    return get_expense(conn, cursor.lastrowid)


def get_expense(conn: sqlite3.Connection, expense_id: int) -> StoredExpense | None:
    row = conn.execute(
        f"SELECT {_EXPENSE_COLUMNS} FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    return StoredExpense(**row) if row else None


def list_expenses(
    conn: sqlite3.Connection,
    *,
    employee_ids: Collection[str] | None = None,
    status: ExpenseStatus | None = None,
) -> list[StoredExpense]:
    """Newest first. `employee_ids=None` means every employee."""
    where, args = ["(? IS NULL OR status = ?)"], [status, status]
    if employee_ids is not None:
        ids = list(employee_ids)
        where.append(f"employee_id IN ({', '.join('?' * len(ids))})")
        args += ids
    rows = conn.execute(
        f"SELECT {_EXPENSE_COLUMNS} FROM expenses WHERE {' AND '.join(where)}"
        " ORDER BY occurred_at_utc DESC, id DESC",
        args,
    )
    return [StoredExpense(**row) for row in rows]


def resolve_expense(
    conn: sqlite3.Connection,
    expense_id: int,
    status: ExpenseStatus,
    resolved_by: str,
) -> None:
    conn.execute(
        "UPDATE expenses SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
        (status, resolved_by, utc_now_iso(), expense_id),
    )


def period_totals(
    conn: sqlite3.Connection,
    employee_id: str,
    category: Category,
    start: datetime,
    end: datetime,
) -> PeriodTotals:
    """Approved and pending sums with `start <= occurred_at < end`. Rejected never counts."""
    row = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN status = 'approved' THEN amount_minor END), 0),"
        " COALESCE(SUM(CASE WHEN status = 'pending' THEN amount_minor END), 0)"
        " FROM expenses"
        " WHERE employee_id = ? AND category = ?"
        " AND occurred_at_utc >= ? AND occurred_at_utc < ?",
        (employee_id, category, to_utc_iso(start), to_utc_iso(end)),
    ).fetchone()
    return PeriodTotals(approved_sum=row[0], pending_sum=row[1])


def insert_decision(conn: sqlite3.Connection, decision: Decision) -> None:
    """Persist the decision of a submitted expense; checks are never stored."""
    if decision.expense_id is None:
        raise ValueError("only decisions of submitted expenses are stored")
    data = decision.model_dump(mode="json")
    conn.execute(
        "INSERT INTO decisions (expense_id, employee_id, policy_id, policy_version,"
        " outcome, reasons, warnings, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["expense_id"],
            data["employee_id"],
            data["policy_id"],
            data["policy_version"],
            data["outcome"],
            json.dumps(data["reasons"]),
            json.dumps(data["warnings"]),
            data["evaluated_at"],
        ),
    )


def get_decision_for_expense(
    conn: sqlite3.Connection, expense_id: int
) -> Decision | None:
    row = conn.execute(
        "SELECT expense_id, employee_id, policy_id, policy_version, outcome, reasons,"
        " warnings, evaluated_at FROM decisions WHERE expense_id = ?",
        (expense_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["reasons"] = json.loads(data["reasons"])
    data["warnings"] = json.loads(data["warnings"])
    return Decision.model_validate(data)

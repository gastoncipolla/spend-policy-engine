"""Expense endpoints: check, submit (idempotent), list, resolve (SPEC §6, §7).

Amounts are integer minor units in JSON (`amount_minor`), never decimals.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from covered.api.deps import Conn
from covered.domain import Decision, ExpenseInput
from covered.domain.errors import InvalidInputError
from covered.services import expenses
from covered.services.expenses import ExpenseWithDecision
from covered.store.records import ExpenseStatus

router = APIRouter(tags=["expenses"])


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["approved", "rejected"]


@router.post("/expenses/check")
def check_expense(body: ExpenseInput, conn: Conn) -> Decision:
    return expenses.check_expense(conn, body)


@router.post("/expenses", status_code=201, response_model=ExpenseWithDecision)
def submit_expense(
    body: ExpenseInput,
    conn: Conn,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Same key + same body replays the stored response; a different body is a 409."""
    if idempotency_key is None:
        raise InvalidInputError("the Idempotency-Key header is required")
    result = expenses.submit_expense(conn, body, idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body)


@router.get("/expenses")
def list_expenses(
    conn: Conn, employee_id: str | None = None, status: ExpenseStatus | None = None
) -> list[ExpenseWithDecision]:
    return expenses.list_expenses(conn, employee_id=employee_id, status=status)


@router.post("/expenses/{expense_id}/resolve")
def resolve_expense(
    expense_id: int, body: ResolveBody, conn: Conn
) -> ExpenseWithDecision:
    return expenses.resolve_expense(conn, expense_id, ExpenseStatus(body.resolution))

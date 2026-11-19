"""Expense endpoints: check, submit (idempotent), list, get, resolve (SPEC §6, §7).

Every endpoint acts as the bearer-token user; the services enforce SPEC §12a.

Amounts are integer minor units in JSON (`amount_minor`), never decimals.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from covered.api.deps import Conn, CurrentActor
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
def check_expense(body: ExpenseInput, conn: Conn, actor: CurrentActor) -> Decision:
    return expenses.check_expense(conn, actor, body)


@router.post("/expenses", status_code=201, response_model=ExpenseWithDecision)
def submit_expense(
    body: ExpenseInput,
    conn: Conn,
    actor: CurrentActor,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Same key + same body replays the stored response; a different body is a 409."""
    if idempotency_key is None:
        raise InvalidInputError("the Idempotency-Key header is required")
    result = expenses.submit_expense(conn, actor, body, idempotency_key)
    return JSONResponse(status_code=result.status_code, content=result.body)


@router.get("/expenses")
def list_expenses(
    conn: Conn,
    actor: CurrentActor,
    employee_id: str | None = None,
    status: ExpenseStatus | None = None,
) -> list[ExpenseWithDecision]:
    """Own (employee), own + team (manager), all (finance)."""
    return expenses.list_expenses(conn, actor, employee_id=employee_id, status=status)


@router.get("/expenses/{expense_id}")
def get_expense(
    expense_id: int, conn: Conn, actor: CurrentActor
) -> ExpenseWithDecision:
    """404 for an expense the caller may not see (its existence is not revealed)."""
    return expenses.get_expense(conn, actor, expense_id)


@router.post("/expenses/{expense_id}/resolve")
def resolve_expense(
    expense_id: int, body: ResolveBody, conn: Conn, actor: CurrentActor
) -> ExpenseWithDecision:
    return expenses.resolve_expense(
        conn, actor, expense_id, ExpenseStatus(body.resolution)
    )

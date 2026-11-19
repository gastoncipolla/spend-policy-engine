"""Turn human CLI input into domain values: decimals and local times."""

from datetime import datetime

import typer

from covered.domain import ExpenseInput
from covered.domain.errors import CoveredError
from covered.domain.money import parse_amount
from covered.services.config import COMPANY_TZ, parse_company_time, utc_now


def parse_occurred_at(value: str | None) -> datetime:
    """ISO 8601. A time without an offset is read in company time; default: now."""
    if value is None:
        return utc_now().astimezone(COMPANY_TZ)
    try:
        return parse_company_time(value)
    except CoveredError as exc:
        raise typer.BadParameter(exc.message, param_hint="--at") from exc


def build_expense(
    *,
    employee: str,
    amount: str,
    category: str,
    at: str | None,
    merchant: str | None,
    justification: str | None,
    pre_approval: str | None,
) -> ExpenseInput:
    """`amount` is a human decimal ("80.00"), converted with Decimal, never float."""
    try:
        amount_minor = parse_amount(amount)
    except CoveredError as exc:
        raise typer.BadParameter(exc.message, param_hint="--amount") from exc
    return ExpenseInput(
        employee_id=employee,
        amount_minor=amount_minor,
        category=category,
        occurred_at=parse_occurred_at(at),
        merchant=merchant,
        justification=justification,
        pre_approval_id=pre_approval,
    )

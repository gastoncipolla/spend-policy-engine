"""Builders shared by service tests (imported as a plain module)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from covered.domain import (
    Category,
    ExpenseInput,
    MaxAmountParams,
    Period,
    PeriodLimitParams,
    PreApprovalThresholdParams,
    ProhibitedCategoryParams,
)
from covered.store.records import Employee, Role

FINANCE = Employee(
    id="fede",
    name="Fede",
    policy_id=None,
    roles=frozenset({Role.EMPLOYEE, Role.FINANCE}),
)
"""A finance actor for policy administration (audit columns have no foreign key)."""

TZ = ZoneInfo("America/Argentina/Buenos_Aires")

POLICY_TEXT = """Ground transport is limited to USD 200 per month.
Ground transport above USD 80 requires pre-approval.
Meals are capped at USD 50 per expense.
Alcohol is never reimbursed.
Prefer partner hotels when possible."""

SAMPLE_RULES = [
    (
        PeriodLimitParams(
            category=Category.GROUND_TRANSPORT, amount_minor=20000, period=Period.MONTH
        ),
        "Ground transport is limited to USD 200 per month.",
    ),
    (
        PreApprovalThresholdParams(
            amount_minor=8000, categories=[Category.GROUND_TRANSPORT]
        ),
        "Ground transport above USD 80 requires pre-approval.",
    ),
    (
        MaxAmountParams(category=Category.MEALS, amount_minor=5000),
        "Meals are capped at USD 50 per expense.",
    ),
    (
        ProhibitedCategoryParams(category=Category.ALCOHOL),
        "Alcohol is never reimbursed.",
    ),
]


def expense(amount_minor: int, category=Category.GROUND_TRANSPORT, **overrides):
    return ExpenseInput(
        employee_id=overrides.pop("employee_id", "ana"),
        amount_minor=amount_minor,
        category=category,
        merchant="Taxi Co",
        occurred_at=overrides.pop(
            "occurred_at", datetime(2026, 11, 18, 10, 0, tzinfo=TZ)
        ),
        **overrides,
    )

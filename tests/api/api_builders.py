"""Builders shared by API tests (imported as a plain module)."""

from covered.domain import (
    Category,
    MaxAmountParams,
    Period,
    PeriodLimitParams,
    PreApprovalThresholdParams,
)
from covered.services.compilation import (
    CompilationSuccess,
    ProposedRule,
    ProposedUncompilable,
)

API_POLICY_TEXT = """Ground transport is limited to USD 200 per month.
Ground transport above USD 80 requires pre-approval.
Meals are capped at USD 50 per expense.
Prefer partner hotels when possible."""


def fake_compiler(text: str) -> CompilationSuccess:
    return CompilationSuccess(
        rules=[
            ProposedRule(
                params=PeriodLimitParams(
                    category=Category.GROUND_TRANSPORT,
                    amount_minor=20000,
                    period=Period.MONTH,
                ),
                clause="Ground transport is limited to USD 200 per month.",
            ),
            ProposedRule(
                params=PreApprovalThresholdParams(
                    amount_minor=8000, categories=[Category.GROUND_TRANSPORT]
                ),
                clause="Ground transport above USD 80 requires pre-approval.",
            ),
            ProposedRule(
                params=MaxAmountParams(category=Category.MEALS, amount_minor=5000),
                clause="Meals are capped at USD 50 per expense.",
            ),
        ],
        uncompilable=[
            ProposedUncompilable(
                clause="Prefer partner hotels when possible.", reason="vague"
            )
        ],
        meta={"model": "fake"},
    )


def approve_all(client, detail):
    for rule in detail["rules"]:
        client.patch(f"/rules/{rule['id']}", json={"status": "approved"})
    for item in detail["uncompilable"]:
        client.patch(
            f"/uncompilable/{item['id']}",
            json={"categories": ["lodging"], "effect": "informational"},
        )

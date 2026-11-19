"""`pre_approval_threshold`: above the threshold without a pre-approval id -> needs_approval.

The MVP trusts any non-blank `pre_approval_id`; verifying it is out of scope.
"""

from covered.domain import ExpenseInput, PreApprovalThresholdParams
from covered.domain.money import format_money
from covered.engine.finding import Finding, needs_approval


def check(params: PreApprovalThresholdParams, expense: ExpenseInput) -> Finding | None:
    if not params.applies_to(expense.category):
        return None
    if expense.amount_minor <= params.amount_minor or expense.has_pre_approval:
        return None
    return needs_approval(
        f"{format_money(expense.amount_minor)} is above the pre-approval threshold of "
        f"{format_money(params.amount_minor)} and has no pre-approval id"
    )

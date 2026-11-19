"""`period_limit`: per-employee cap per calendar month / ISO week (SPEC §4.3).

if approved_sum + amount > limit:                 rejected
elif approved_sum + pending_sum + amount > limit: needs_approval
else:                                             pass
"""

from covered.domain import ExpenseInput, PeriodHistory, PeriodLimitParams
from covered.domain.money import format_money
from covered.engine.finding import Finding, needs_approval, rejected

_PERIOD_ADJECTIVE = {"month": "monthly", "week": "weekly"}


def check(
    params: PeriodLimitParams, expense: ExpenseInput, history: PeriodHistory
) -> Finding | None:
    if expense.category != params.category:
        return None
    totals = history.totals_for(params.period)
    limit = params.amount_minor
    amount = expense.amount_minor
    label = f"the {_PERIOD_ADJECTIVE[params.period]} limit of {format_money(limit)} for {params.category}"

    if totals.approved_sum + amount > limit:
        return rejected(
            f"Exceeds {label}: already approved {format_money(totals.approved_sum)} "
            f"+ this {format_money(amount)} = {format_money(totals.approved_sum + amount)}"
        )
    if totals.approved_sum + totals.pending_sum + amount > limit:
        return needs_approval(
            f"Exceeds {label} if pending expenses of "
            f"{format_money(totals.pending_sum)} are approved"
        )
    return None

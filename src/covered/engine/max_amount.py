"""`max_amount`: an expense above the cap is rejected; equal passes."""

from covered.domain import ExpenseInput, MaxAmountParams
from covered.domain.money import format_money
from covered.engine.finding import Finding, rejected


def check(params: MaxAmountParams, expense: ExpenseInput) -> Finding | None:
    if (
        expense.category != params.category
        or expense.amount_minor <= params.amount_minor
    ):
        return None
    return rejected(
        f"{format_money(expense.amount_minor)} exceeds the maximum of "
        f"{format_money(params.amount_minor)} per expense for {params.category}"
    )

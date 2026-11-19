"""`prohibited_category`: any expense in the category is rejected."""

from covered.domain import ExpenseInput, ProhibitedCategoryParams
from covered.engine.finding import Finding, rejected


def check(params: ProhibitedCategoryParams, expense: ExpenseInput) -> Finding | None:
    if expense.category != params.category:
        return None
    return rejected(f"Expenses in {params.category} are not reimbursable")

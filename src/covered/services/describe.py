"""Human-readable descriptions shared by the CLI and the pages."""

from covered.domain import CATEGORY_NAMES, Outcome, RuleParams
from covered.domain.money import format_money
from covered.domain.rules import (
    MaxAmountParams,
    PeriodLimitParams,
    PreApprovalThresholdParams,
    ProhibitedCategoryParams,
    TimeRestrictionParams,
)

OUTCOME_LABELS = {
    Outcome.APPROVED: "Approved",
    Outcome.NEEDS_APPROVAL: "Needs approval",
    Outcome.REJECTED: "Rejected",
}

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def category_name(code: str) -> str:
    if code == "*":
        return "All categories"
    return CATEGORY_NAMES.get(code, code)


def categories_text(codes: list[str] | None) -> str:
    if not codes:
        return "All categories"
    return ", ".join(category_name(code) for code in codes)


def describe_rule(params: RuleParams) -> str:
    """One line, e.g. "Meals: at most USD 80.00 per expense"."""
    match params:
        case MaxAmountParams():
            amount = format_money(params.amount_minor)
            return f"{category_name(params.category)}: at most {amount} per expense"
        case ProhibitedCategoryParams():
            return f"{category_name(params.category)}: not reimbursable"
        case PreApprovalThresholdParams():
            amount = format_money(params.amount_minor)
            scope = categories_text(params.categories)
            return f"{scope}: pre-approval needed above {amount}"
        case PeriodLimitParams():
            amount = format_money(params.amount_minor)
            return f"{category_name(params.category)}: {amount} per {params.period}"
        case TimeRestrictionParams():
            return f"{categories_text(params.categories)}: {_time_window(params)}"
    return str(params)


def _time_window(params: TimeRestrictionParams) -> str:
    days = ", ".join(WEEKDAYS[day] for day in sorted(params.allowed_weekdays))
    text = f"only on {days}"
    if params.allowed_hours is not None:
        text += f", {params.allowed_hours.start}-{params.allowed_hours.end}"
    if params.justification_allows_review:
        text += " (with a justification: review)"
    return text

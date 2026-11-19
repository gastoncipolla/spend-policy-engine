"""`time_restriction`: only on allowed weekdays/hours, judged in company time.

Outside the window -> rejected, unless the rule allows review and the expense
has a non-blank justification -> needs_approval.
"""

from zoneinfo import ZoneInfo

from covered.domain import ExpenseInput, TimeRestrictionParams
from covered.engine.finding import Finding, needs_approval, rejected

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def check(
    params: TimeRestrictionParams, expense: ExpenseInput, tz: ZoneInfo
) -> Finding | None:
    if not params.applies_to(expense.category):
        return None
    local = expense.occurred_at.astimezone(tz)
    day_allowed = local.weekday() in params.allowed_weekdays
    hour_allowed = params.allowed_hours is None or params.allowed_hours.contains(
        local.time()
    )
    if day_allowed and hour_allowed:
        return None

    message = (
        f"{expense.category} expenses are allowed only {_describe(params)}; "
        f"this one occurred {_DAY_NAMES[local.weekday()]} {local:%H:%M} (company time)"
    )
    if params.justification_allows_review and expense.has_justification:
        return needs_approval(f"{message}. Justification provided, review required")
    return rejected(message)


def _describe(params: TimeRestrictionParams) -> str:
    days = ", ".join(_DAY_NAMES[day] for day in sorted(params.allowed_weekdays))
    if params.allowed_hours is None:
        return f"on {days}"
    return f"on {days} {params.allowed_hours.start}-{params.allowed_hours.end}"

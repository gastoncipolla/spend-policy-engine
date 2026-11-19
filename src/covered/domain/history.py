"""Period history consumed by `period_limit` rules (SPEC §4.3).

The caller (store/service) sums the employee's stored expenses in the expense's
category whose `occurred_at` falls in the same period window
(see `covered.engine.periods.period_window`). Rejected expenses and checks
(simulations) never count, and the expense being evaluated must not be included.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from covered.domain.rules import Period

NonNegativeMinor = Annotated[int, Field(strict=True, ge=0)]


class PeriodTotals(BaseModel):
    """Sums in minor units for one period window."""

    model_config = ConfigDict(frozen=True)

    approved_sum: NonNegativeMinor = 0
    pending_sum: NonNegativeMinor = 0


class PeriodHistory(BaseModel):
    """Totals for the expense's category in its current month and ISO week."""

    model_config = ConfigDict(frozen=True)

    month: PeriodTotals = PeriodTotals()
    week: PeriodTotals = PeriodTotals()

    def totals_for(self, period: Period) -> PeriodTotals:
        return self.month if period is Period.MONTH else self.week

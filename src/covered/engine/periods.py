"""Period windows for `period_limit` history queries (SPEC §4.3).

Month = calendar month, week = ISO week (Monday 00:00 to next Monday 00:00),
both in company time. The store sums expenses with `start <= occurred_at < end`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from covered.domain import Period


@dataclass(frozen=True)
class PeriodWindow:
    """Half-open interval `[start, end)` as tz-aware datetimes in company time."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


def period_window(occurred_at: datetime, period: Period, tz: ZoneInfo) -> PeriodWindow:
    """Return the month or ISO-week window containing `occurred_at` in `tz`.

    `occurred_at` must be timezone-aware. Boundaries are local midnights, so
    they stay correct across DST changes.
    """
    if occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    local = occurred_at.astimezone(tz)
    day = local.date()
    if period is Period.MONTH:
        first = day.replace(day=1)
        next_first = (first + timedelta(days=32)).replace(day=1)
    else:
        first = day - timedelta(days=day.weekday())
        next_first = first + timedelta(days=7)
    return PeriodWindow(_midnight(first, tz), _midnight(next_first, tz))


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz)

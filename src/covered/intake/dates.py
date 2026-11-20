"""Resolve the provider's date description against a given `now` (pure, no clock).

"Today" is the calendar day of `now` in the company timezone, not in UTC: at
23:00 in Buenos Aires (02:00 UTC the next day) "ayer" is still the day before
the local date.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from covered.intake.schema import DateKind, IntakePayload

DEFAULT_TIME = time(12, 0)
"""Time used when the text gives a date but no time (flagged for review)."""


def resolve_day(payload: IntakePayload, today: date) -> date | None:
    """The calendar day the payload describes, or None if absent or impossible.

    - previous_weekday: the most recent such weekday strictly before today
      ("el sábado" said on a Saturday means a week ago; today would be "hoy").
    - calendar_date without a year: the most recent such day on or before today.
    """
    try:
        match payload.date_kind:
            case DateKind.RELATIVE_DAYS if payload.offset_days is not None:
                return today + timedelta(days=payload.offset_days)
            case DateKind.PREVIOUS_WEEKDAY if payload.weekday in range(7):
                back = (today.weekday() - payload.weekday) % 7 or 7
                return today - timedelta(days=back)
            case DateKind.CALENDAR_DATE if payload.day and payload.month:
                if payload.year is not None:
                    return date(payload.year, payload.month, payload.day)
                candidate = date(today.year, payload.month, payload.day)
                if candidate > today:
                    candidate = date(today.year - 1, payload.month, payload.day)
                return candidate
    except (ValueError, OverflowError):  # 31/02, year 0, huge offsets...
        return None
    return None


def parse_clock(value: str | None) -> time | None:
    """ "21:30" -> time(21, 30); anything else -> None."""
    if value is None:
        return None
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        return None


def local_moment(day: date, clock: time | None, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, clock or DEFAULT_TIME, tzinfo=tz)

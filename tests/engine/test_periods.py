"""Period windows in company time (calendar month, ISO week)."""

from datetime import UTC, datetime

import pytest
from engine_builders import TZ

from covered.domain import Period
from covered.engine import period_window


def local(*args):
    return datetime(*args, tzinfo=TZ)


def test_month_window():
    window = period_window(local(2026, 11, 18, 12, 0), Period.MONTH, TZ)
    assert (window.start, window.end) == (local(2026, 11, 1), local(2026, 12, 1))


def test_december_rolls_into_next_year():
    window = period_window(local(2026, 12, 31, 23, 59), Period.MONTH, TZ)
    assert window.end == local(2027, 1, 1)


def test_iso_week_window_monday_to_monday():
    window = period_window(local(2026, 11, 22, 23, 30), Period.WEEK, TZ)  # Sunday
    assert (window.start, window.end) == (local(2026, 11, 16), local(2026, 11, 23))


def test_window_uses_company_time_not_utc():
    """Sunday 23:30 local is Monday 02:30 UTC but belongs to the local week."""
    moment = local(2026, 11, 22, 23, 30).astimezone(UTC)
    window = period_window(moment, Period.WEEK, TZ)
    assert window.start == local(2026, 11, 16)
    assert window.contains(moment) and not window.contains(window.end)


def test_month_edge_in_company_time():
    """Nov 30 22:00 local is Dec 1 in UTC but belongs to November."""
    moment = local(2026, 11, 30, 22, 0).astimezone(UTC)
    assert period_window(moment, Period.MONTH, TZ).start == local(2026, 11, 1)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        period_window(datetime(2026, 11, 1), Period.MONTH, TZ)

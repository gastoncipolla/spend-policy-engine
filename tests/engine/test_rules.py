"""One test group per rule type, through `evaluate` so reasons carry rule ids and clauses."""

from datetime import UTC, datetime

import pytest
from engine_builders import NOW, TZ, expense, policy, rule

from covered.domain import Outcome, PeriodHistory, PeriodTotals
from covered.engine import evaluate

MEALS_CAP = rule(1, type="max_amount", category="meals", amount_minor=10000)


NO_HISTORY = PeriodHistory()


def run(exp, *rules, history=NO_HISTORY):
    return evaluate(exp, policy(*rules), history, TZ, NOW)


# max_amount


@pytest.mark.parametrize(
    ("amount", "outcome"),
    [(9999, Outcome.APPROVED), (10000, Outcome.APPROVED), (10001, Outcome.REJECTED)],
)
def test_max_amount_boundary(amount, outcome):
    decision = run(expense(amount_minor=amount), MEALS_CAP)
    assert decision.outcome is outcome


def test_max_amount_reason_cites_rule_and_clause():
    decision = run(expense(amount_minor=10001), MEALS_CAP)
    [reason] = decision.reasons
    assert (reason.rule_id, reason.clause) == (1, "clause 1")
    assert "USD 100.01" in reason.message and "USD 100.00" in reason.message


def test_max_amount_ignores_other_categories():
    other_cap = rule(2, type="max_amount", category="lodging", amount_minor=100)
    decision = run(expense(amount_minor=5000), MEALS_CAP, other_cap)
    assert decision.outcome is Outcome.APPROVED


# prohibited_category


def test_prohibited_category_rejects_matching_category():
    prohibited = rule(2, type="prohibited_category", category="alcohol")
    decision = run(expense(category="alcohol", amount_minor=1), prohibited)
    assert decision.outcome is Outcome.REJECTED
    assert decision.reasons[0].rule_id == 2


def test_prohibited_category_ignores_other_categories():
    prohibited = rule(2, type="prohibited_category", category="alcohol")
    assert run(expense(), MEALS_CAP, prohibited).outcome is Outcome.APPROVED


# pre_approval_threshold


def threshold(categories=None):
    return rule(
        3,
        type="pre_approval_threshold",
        amount_minor=8000,
        categories=categories,
    )


@pytest.mark.parametrize(
    ("amount", "outcome"),
    [(8000, Outcome.APPROVED), (8001, Outcome.NEEDS_APPROVAL)],
)
def test_pre_approval_threshold_boundary(amount, outcome):
    decision = run(expense(amount_minor=amount), MEALS_CAP, threshold())
    assert decision.outcome is outcome


def test_pre_approval_id_passes_threshold():
    exp = expense(amount_minor=9000, pre_approval_id="PA-1")
    assert run(exp, MEALS_CAP, threshold()).outcome is Outcome.APPROVED


def test_blank_pre_approval_id_does_not_count():
    exp = expense(amount_minor=9000, pre_approval_id="  ")
    assert run(exp, MEALS_CAP, threshold()).outcome is Outcome.NEEDS_APPROVAL


def test_threshold_limited_to_categories():
    exp = expense(amount_minor=9000)
    decision = run(exp, MEALS_CAP, threshold(categories=["lodging"]))
    assert decision.outcome is Outcome.APPROVED


# period_limit

MONTHLY = rule(
    4, type="period_limit", category="meals", amount_minor=20000, period="month"
)


def month(approved=0, pending=0):
    return PeriodHistory(month=PeriodTotals(approved_sum=approved, pending_sum=pending))


@pytest.mark.parametrize(
    ("history", "outcome"),
    [
        (month(approved=15000), Outcome.APPROVED),  # 150 + 50 = 200, equal passes
        (month(approved=15001), Outcome.REJECTED),
        (month(approved=10000, pending=5000), Outcome.APPROVED),  # 100+50+50 = 200
        (month(approved=10000, pending=5001), Outcome.NEEDS_APPROVAL),
        (month(approved=15001, pending=9999), Outcome.REJECTED),
    ],
)
def test_period_limit(history, outcome):
    assert run(expense(), MONTHLY, history=history).outcome is outcome


def test_period_limit_uses_its_own_period_totals():
    weekly = rule(
        5, type="period_limit", category="meals", amount_minor=6000, period="week"
    )
    history = PeriodHistory(
        month=PeriodTotals(approved_sum=99999), week=PeriodTotals(approved_sum=1000)
    )
    assert run(expense(), weekly, history=history).outcome is Outcome.APPROVED


# time_restriction


def weekdays_rule(allows_review: bool, hours=None):
    return rule(
        6,
        type="time_restriction",
        categories=["meals"],
        allowed_weekdays=[0, 1, 2, 3, 4],
        allowed_hours=hours,
        justification_allows_review=allows_review,
    )


SUNDAY_2330_LOCAL = datetime(2026, 11, 22, 23, 30, tzinfo=TZ)


def test_time_restriction_inside_window_passes():
    hours = {"start": "08:00", "end": "22:00"}
    decision = run(expense(), MEALS_CAP, weekdays_rule(False, hours))
    assert decision.outcome is Outcome.APPROVED


def test_time_restriction_outside_hours_rejected():
    hours = {"start": "08:00", "end": "22:00"}
    late = expense(occurred_at=datetime(2026, 11, 18, 22, 0, tzinfo=TZ))
    assert run(late, MEALS_CAP, weekdays_rule(False, hours)).outcome is Outcome.REJECTED


def test_time_restriction_without_justification_rejected():
    exp = expense(occurred_at=SUNDAY_2330_LOCAL)
    assert run(exp, MEALS_CAP, weekdays_rule(True)).outcome is Outcome.REJECTED


def test_time_restriction_with_justification_needs_approval():
    exp = expense(occurred_at=SUNDAY_2330_LOCAL, justification="client dinner")
    assert run(exp, MEALS_CAP, weekdays_rule(True)).outcome is Outcome.NEEDS_APPROVAL


def test_time_restriction_justification_ignored_when_review_not_allowed():
    exp = expense(occurred_at=SUNDAY_2330_LOCAL, justification="client dinner")
    assert run(exp, MEALS_CAP, weekdays_rule(False)).outcome is Outcome.REJECTED


def test_time_restriction_blank_justification_rejected():
    exp = expense(occurred_at=SUNDAY_2330_LOCAL, justification="   ")
    assert run(exp, MEALS_CAP, weekdays_rule(True)).outcome is Outcome.REJECTED


def test_timezone_edge_sunday_2330_local_is_monday_in_utc():
    """23:30 Sunday in Buenos Aires is 02:30 Monday UTC: the company day wins."""
    utc = SUNDAY_2330_LOCAL.astimezone(UTC)
    assert utc.weekday() == 0
    decision = run(expense(occurred_at=utc), MEALS_CAP, weekdays_rule(False))
    assert decision.outcome is Outcome.REJECTED
    assert "Sun 23:30" in decision.reasons[0].message

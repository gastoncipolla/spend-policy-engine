from datetime import UTC, datetime, time

import pytest
from pydantic import TypeAdapter, ValidationError

from covered.domain import (
    Category,
    CompiledPolicy,
    ConfirmedUncompilable,
    Decision,
    ExpenseInput,
    MaxAmountParams,
    Outcome,
    Period,
    PeriodHistory,
    PeriodLimitParams,
    PeriodTotals,
    PolicyRule,
    PreApprovalThresholdParams,
    ProhibitedCategoryParams,
    Reason,
    ReasonSource,
    RuleParams,
    RuleType,
    TimeRestrictionParams,
    TimeWindow,
)

RULE_PARAMS = TypeAdapter(RuleParams)


# --- rule params: discriminated union and validation ---------------------------------


@pytest.mark.parametrize(
    ("payload", "model"),
    [
        (
            {"type": "max_amount", "category": "meals", "amount_minor": 5000},
            MaxAmountParams,
        ),
        (
            {"type": "prohibited_category", "category": "alcohol"},
            ProhibitedCategoryParams,
        ),
        (
            {
                "type": "pre_approval_threshold",
                "amount_minor": 8000,
                "categories": None,
            },
            PreApprovalThresholdParams,
        ),
        (
            {
                "type": "period_limit",
                "category": "ground_transport",
                "amount_minor": 20000,
                "period": "month",
            },
            PeriodLimitParams,
        ),
        (
            {
                "type": "time_restriction",
                "categories": ["meals"],
                "allowed_weekdays": [0, 1, 2, 3, 4],
                "allowed_hours": {"start": "08:00", "end": "22:00"},
                "justification_allows_review": True,
            },
            TimeRestrictionParams,
        ),
    ],
)
def test_union_dispatches_on_type(payload, model):
    params = RULE_PARAMS.validate_python(payload)
    assert isinstance(params, model)
    assert RULE_PARAMS.validate_json(RULE_PARAMS.dump_json(params)) == params


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "unknown_rule", "category": "meals"},
        {"type": "max_amount", "category": "meals", "amount_minor": 0},
        {"type": "max_amount", "category": "meals", "amount_minor": -1},
        {"type": "max_amount", "category": "meals", "amount_minor": 10.5},
        {"type": "max_amount", "category": "groceries", "amount_minor": 100},
        {"type": "max_amount", "category": "meals", "amount_minor": 100, "extra": 1},
        {"type": "pre_approval_threshold", "amount_minor": 100, "categories": []},
        {
            "type": "pre_approval_threshold",
            "amount_minor": 100,
            "categories": ["meals", "meals"],
        },
        {
            "type": "period_limit",
            "category": "meals",
            "amount_minor": 100,
            "period": "year",
        },
        {"type": "time_restriction", "allowed_weekdays": []},
        {"type": "time_restriction", "allowed_weekdays": [7]},
        {"type": "time_restriction", "allowed_weekdays": [1, 1]},
        {
            "type": "time_restriction",
            "allowed_weekdays": [0],
            "allowed_hours": {"start": "8:00", "end": "22:00"},
        },
        {
            "type": "time_restriction",
            "allowed_weekdays": [0],
            "allowed_hours": {"start": "10:00", "end": "10:00"},
        },
    ],
)
def test_invalid_params_are_rejected(payload):
    with pytest.raises(ValidationError):
        RULE_PARAMS.validate_python(payload)


def test_explicit_categories():
    assert MaxAmountParams(category="meals", amount_minor=1).explicit_categories() == {
        Category.MEALS
    }
    assert (
        PreApprovalThresholdParams(amount_minor=1).explicit_categories() == frozenset()
    )
    restriction = TimeRestrictionParams(
        categories=["meals", "alcohol"], allowed_weekdays=[0]
    )
    assert restriction.explicit_categories() == {Category.MEALS, Category.ALCOHOL}


def test_time_window_is_start_inclusive_end_exclusive():
    window = TimeWindow(start="08:00", end="22:00")
    assert window.contains(time(8, 0))
    assert window.contains(time(21, 59, 59))
    assert not window.contains(time(22, 0))
    assert not window.contains(time(7, 59))


def test_time_window_can_wrap_midnight():
    window = TimeWindow(start="22:00", end="06:00")
    assert window.contains(time(23, 30))
    assert window.contains(time(5, 59))
    assert not window.contains(time(6, 0))
    assert not window.contains(time(12, 0))


def test_policy_rule_exposes_type():
    rule = PolicyRule(
        id=1,
        clause="No alcohol.",
        params={"type": "prohibited_category", "category": "alcohol"},
    )
    assert rule.type is RuleType.PROHIBITED_CATEGORY


# --- uncompilable and compiled policy -------------------------------------------------


def test_uncompilable_star_applies_to_everything():
    item = ConfirmedUncompilable(
        id=1, clause="x", reason="vague", categories=["*"], effect="informational"
    )
    assert all(item.applies_to(category) for category in Category)


def test_uncompilable_star_cannot_be_mixed():
    with pytest.raises(ValidationError):
        ConfirmedUncompilable(
            id=1,
            clause="x",
            reason="vague",
            categories=["*", "meals"],
            effect="informational",
        )


def test_uncompilable_unknown_category_is_rejected():
    with pytest.raises(ValidationError):
        ConfirmedUncompilable(
            id=1,
            clause="x",
            reason="vague",
            categories=["yachts"],
            effect="informational",
        )


def test_compiled_policy_uncovered_categories():
    policy = CompiledPolicy(
        policy_id=1,
        version=1,
        rules=[
            PolicyRule(
                id=1,
                clause="a",
                params={"type": "max_amount", "category": "meals", "amount_minor": 1},
            ),
            PolicyRule(
                id=2,
                clause="b",
                params={"type": "pre_approval_threshold", "amount_minor": 1},
            ),
            PolicyRule(
                id=3,
                clause="c",
                params={"type": "prohibited_category", "category": "other"},
            ),
        ],
    )
    uncovered = policy.uncovered_categories()
    assert Category.MEALS not in uncovered
    assert Category.OTHER in uncovered
    assert Category.LODGING in uncovered


def test_compiled_policy_rejects_duplicate_ids():
    rule = PolicyRule(
        id=1, clause="a", params={"type": "prohibited_category", "category": "alcohol"}
    )
    with pytest.raises(ValidationError):
        CompiledPolicy(policy_id=1, version=1, rules=[rule, rule])


# --- expense, history, decision -------------------------------------------------------


def _expense(**overrides):
    data = {
        "employee_id": "ana",
        "amount_minor": 1000,
        "category": "meals",
        "occurred_at": datetime(2026, 11, 20, 12, tzinfo=UTC),
    }
    return ExpenseInput(**(data | overrides))


def test_expense_defaults_to_company_currency():
    assert _expense().currency == "USD"


@pytest.mark.parametrize(
    "overrides",
    [
        {"currency": "EUR"},
        {"amount_minor": 0},
        {"amount_minor": 10.0},
        {"category": "groceries"},
        {"occurred_at": datetime(2026, 11, 20, 12)},
    ],
)
def test_expense_validation(overrides):
    with pytest.raises(ValidationError):
        _expense(**overrides)


def test_blank_justification_and_pre_approval_do_not_count():
    expense = _expense(justification="   ", pre_approval_id="")
    assert not expense.has_justification
    assert not expense.has_pre_approval
    assert _expense(
        justification="client dinner", pre_approval_id="PA-1"
    ).has_pre_approval


def test_period_history_selects_totals():
    history = PeriodHistory(
        month=PeriodTotals(approved_sum=5), week=PeriodTotals(pending_sum=7)
    )
    assert history.totals_for(Period.MONTH).approved_sum == 5
    assert history.totals_for(Period.WEEK).pending_sum == 7
    assert PeriodHistory().totals_for(Period.MONTH) == PeriodTotals()


def test_reason_fields_must_match_source():
    Reason(source="uncovered_category", outcome="needs_approval", message="No rule")
    with pytest.raises(ValidationError):
        Reason(source="rule", outcome="rejected", message="missing rule id")
    with pytest.raises(ValidationError):
        Reason(
            source="rule",
            rule_id=1,
            clause="c",
            outcome="approved",
            message="not a reason",
        )


def test_decision_round_trips_through_json():
    decision = Decision(
        employee_id="ana",
        policy_id=1,
        policy_version=2,
        outcome=Outcome.NEEDS_APPROVAL,
        reasons=[
            Reason(
                source=ReasonSource.RULE,
                rule_id=3,
                clause="c",
                outcome=Outcome.NEEDS_APPROVAL,
                message="m",
            )
        ],
        warnings=[],
        evaluated_at=datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert Decision.model_validate_json(decision.model_dump_json()) == decision

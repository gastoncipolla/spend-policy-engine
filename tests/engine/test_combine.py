"""Combination (SPEC §4.2), the §4.3 worked example, coverage and uncompilable clauses."""

from engine_builders import NOW, TZ, expense, policy, rule

from covered.domain import (
    ConfirmedUncompilable,
    Outcome,
    PeriodHistory,
    PeriodTotals,
    ReasonSource,
)
from covered.engine import UNCOVERED_MESSAGE, evaluate

MEALS_CAP = rule(1, type="max_amount", category="meals", amount_minor=10000)
THRESHOLD = rule(2, type="pre_approval_threshold", amount_minor=8000)


def test_no_reasons_means_approved_with_policy_reference():
    decision = evaluate(expense(), policy(MEALS_CAP), PeriodHistory(), TZ, NOW)
    assert decision.outcome is Outcome.APPROVED
    assert decision.reasons == [] and decision.warnings == []
    assert (decision.policy_id, decision.policy_version) == (1, 1)
    assert decision.evaluated_at == NOW and decision.employee_id == "ana"


def test_rejected_wins_and_all_reasons_are_returned():
    decision = evaluate(
        expense(amount_minor=12000),
        policy(MEALS_CAP, THRESHOLD),
        PeriodHistory(),
        TZ,
        NOW,
    )
    assert decision.outcome is Outcome.REJECTED
    assert [(r.rule_id, r.outcome) for r in decision.reasons] == [
        (1, Outcome.REJECTED),
        (2, Outcome.NEEDS_APPROVAL),
    ]


def test_needs_approval_wins_over_approved():
    decision = evaluate(
        expense(amount_minor=9000),
        policy(MEALS_CAP, THRESHOLD),
        PeriodHistory(),
        TZ,
        NOW,
    )
    assert decision.outcome is Outcome.NEEDS_APPROVAL


def test_worked_example_period_limit_with_pending():
    """SPEC §4.3: limit 200/month on ground_transport plus threshold 80."""
    rules = policy(
        rule(
            1,
            type="period_limit",
            category="ground_transport",
            amount_minor=20000,
            period="month",
        ),
        rule(
            2,
            type="pre_approval_threshold",
            amount_minor=8000,
            categories=["ground_transport"],
        ),
    )

    def taxi(amount, approved, pending):
        history = PeriodHistory(
            month=PeriodTotals(approved_sum=approved, pending_sum=pending)
        )
        exp = expense(category="ground_transport", amount_minor=amount)
        return evaluate(exp, rules, history, TZ, NOW)

    assert taxi(6000, 0, 0).outcome is Outcome.APPROVED

    second = taxi(9000, 6000, 0)
    assert second.outcome is Outcome.NEEDS_APPROVAL
    assert [r.rule_id for r in second.reasons] == [2]

    third = taxi(7000, 6000, 9000)
    assert third.outcome is Outcome.NEEDS_APPROVAL
    [reason] = third.reasons
    assert reason.rule_id == 1
    assert "if pending expenses of USD 90.00 are approved" in reason.message


def test_uncovered_category_needs_approval():
    decision = evaluate(
        expense(category="software"), policy(MEALS_CAP), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.NEEDS_APPROVAL
    [reason] = decision.reasons
    assert reason.source is ReasonSource.UNCOVERED_CATEGORY
    assert reason.message == UNCOVERED_MESSAGE and reason.clause is None


def test_rules_for_all_categories_do_not_cover():
    decision = evaluate(
        expense(category="software"), policy(THRESHOLD), PeriodHistory(), TZ, NOW
    )
    assert decision.reasons[-1].source is ReasonSource.UNCOVERED_CATEGORY


def test_other_is_never_covered():
    other_cap = rule(3, type="max_amount", category="other", amount_minor=10000)
    decision = evaluate(
        expense(category="other"), policy(other_cap), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.NEEDS_APPROVAL
    assert decision.reasons[0].source is ReasonSource.UNCOVERED_CATEGORY


def test_uncovered_does_not_hide_rejection():
    prohibited = rule(3, type="prohibited_category", category="other")
    decision = evaluate(
        expense(category="other"), policy(prohibited), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.REJECTED
    assert len(decision.reasons) == 2


def clause(item_id, effect, categories):
    return ConfirmedUncompilable(
        id=item_id,
        clause=f"uncompilable {item_id}",
        reason="ambiguous",
        categories=categories,
        effect=effect,
    )


def test_requires_review_clause_adds_needs_approval_reason():
    review = clause(10, "requires_review", ["meals"])
    decision = evaluate(
        expense(), policy(MEALS_CAP, uncompilable=[review]), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.NEEDS_APPROVAL
    [reason] = decision.reasons
    assert reason.source is ReasonSource.UNCOMPILABLE
    assert (reason.uncompilable_id, reason.clause) == (10, "uncompilable 10")


def test_informational_clause_adds_warning_only():
    info = clause(11, "informational", ["*"])
    decision = evaluate(
        expense(), policy(MEALS_CAP, uncompilable=[info]), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.APPROVED
    [warning] = decision.warnings
    assert (warning.uncompilable_id, warning.clause) == (11, "uncompilable 11")


def test_uncompilable_for_other_categories_is_ignored():
    items = [
        clause(10, "requires_review", ["airfare"]),
        clause(11, "informational", ["lodging"]),
    ]
    decision = evaluate(
        expense(), policy(MEALS_CAP, uncompilable=items), PeriodHistory(), TZ, NOW
    )
    assert decision.outcome is Outcome.APPROVED
    assert decision.warnings == []

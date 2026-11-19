"""`evaluate`: run every rule, add uncompilable and coverage reasons, combine (SPEC §4.2).

Pure: no I/O, no clock. The caller passes `evaluated_at`.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from covered.domain import (
    OUTCOME_PRECEDENCE,
    Category,
    CompiledPolicy,
    Decision,
    DecisionWarning,
    ExpenseInput,
    Outcome,
    PeriodHistory,
    PolicyRule,
    Reason,
    ReasonSource,
    UncompilableEffect,
)
from covered.engine import (
    max_amount,
    period_limit,
    pre_approval_threshold,
    prohibited_category,
    time_restriction,
)
from covered.engine.finding import Finding

UNCOVERED_MESSAGE = "No rule covers this category"


def evaluate(
    expense: ExpenseInput,
    policy: CompiledPolicy,
    history: PeriodHistory,
    tz: ZoneInfo,
    evaluated_at: datetime,
) -> Decision:
    """Evaluate one expense against one compiled policy version.

    Returns every non-pass reason (rules in policy order, then uncompilable
    clauses, then the uncovered-category reason) and the outcome with
    precedence rejected > needs_approval > approved.
    """
    reasons = [
        _rule_reason(rule, finding)
        for rule in policy.rules
        if (finding := _check(rule, expense, history, tz)) is not None
    ]
    warnings: list[DecisionWarning] = []
    for item in policy.uncompilable:
        if not item.applies_to(expense.category):
            continue
        if item.effect is UncompilableEffect.REQUIRES_REVIEW:
            reasons.append(
                Reason(
                    source=ReasonSource.UNCOMPILABLE,
                    uncompilable_id=item.id,
                    clause=item.clause,
                    outcome=Outcome.NEEDS_APPROVAL,
                    message="This policy clause requires manual review",
                )
            )
        else:
            warnings.append(
                DecisionWarning(
                    uncompilable_id=item.id,
                    clause=item.clause,
                    message="Keep this policy clause in mind",
                )
            )
    if (
        expense.category is Category.OTHER
        or expense.category not in policy.covered_categories()
    ):
        reasons.append(
            Reason(
                source=ReasonSource.UNCOVERED_CATEGORY,
                outcome=Outcome.NEEDS_APPROVAL,
                message=UNCOVERED_MESSAGE,
            )
        )
    return Decision(
        employee_id=expense.employee_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        outcome=_combine(reasons),
        reasons=reasons,
        warnings=warnings,
        evaluated_at=evaluated_at,
    )


def _check(
    rule: PolicyRule, expense: ExpenseInput, history: PeriodHistory, tz: ZoneInfo
) -> Finding | None:
    params = rule.params
    match params.type:
        case "max_amount":
            return max_amount.check(params, expense)
        case "prohibited_category":
            return prohibited_category.check(params, expense)
        case "pre_approval_threshold":
            return pre_approval_threshold.check(params, expense)
        case "period_limit":
            return period_limit.check(params, expense, history)
        case "time_restriction":
            return time_restriction.check(params, expense, tz)
    raise AssertionError(f"unknown rule type {params.type!r}")


def _rule_reason(rule: PolicyRule, finding: Finding) -> Reason:
    return Reason(
        source=ReasonSource.RULE,
        rule_id=rule.id,
        clause=rule.clause,
        outcome=finding.outcome,
        message=finding.message,
    )


def _combine(reasons: list[Reason]) -> Outcome:
    return max(
        (reason.outcome for reason in reasons),
        key=OUTCOME_PRECEDENCE.__getitem__,
        default=Outcome.APPROVED,
    )

"""Domain model: categories, money, rules, policies, expenses, decisions, errors.

Import from here; submodules are an implementation detail.
"""

from covered.domain.categories import CATEGORY_NAMES, Category
from covered.domain.decision import (
    OUTCOME_PRECEDENCE,
    Decision,
    DecisionWarning,
    Outcome,
    Reason,
    ReasonSource,
)
from covered.domain.expense import ExpenseInput
from covered.domain.history import PeriodHistory, PeriodTotals
from covered.domain.policy import (
    ALL_CATEGORIES,
    CompiledPolicy,
    ConfirmedUncompilable,
    UncompilableEffect,
)
from covered.domain.rules import (
    MaxAmountParams,
    Period,
    PeriodLimitParams,
    PolicyRule,
    PreApprovalThresholdParams,
    ProhibitedCategoryParams,
    RuleParams,
    RuleType,
    TimeRestrictionParams,
    TimeWindow,
)

__all__ = [
    "ALL_CATEGORIES",
    "CATEGORY_NAMES",
    "OUTCOME_PRECEDENCE",
    "Category",
    "CompiledPolicy",
    "ConfirmedUncompilable",
    "Decision",
    "DecisionWarning",
    "ExpenseInput",
    "MaxAmountParams",
    "Outcome",
    "Period",
    "PeriodHistory",
    "PeriodLimitParams",
    "PeriodTotals",
    "PolicyRule",
    "PreApprovalThresholdParams",
    "ProhibitedCategoryParams",
    "Reason",
    "ReasonSource",
    "RuleParams",
    "RuleType",
    "TimeRestrictionParams",
    "TimeWindow",
    "UncompilableEffect",
]

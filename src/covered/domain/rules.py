"""The five rule types (SPEC §3) as a Pydantic discriminated union.

`RuleParams` is the union; `type` is the discriminator. Every params model is
frozen, forbids unknown fields, requires amounts > 0 (and <= MAX_AMOUNT_MINOR) and categories from the
catalog. `PolicyRule` is an approved rule as the engine sees it.
"""

from datetime import time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from covered.domain.categories import Category
from covered.domain.money import MAX_AMOUNT_MINOR

PositiveMinor = Annotated[int, Field(strict=True, gt=0, le=MAX_AMOUNT_MINOR)]
"""Positive amount in minor units, capped at `MAX_AMOUNT_MINOR` (floats and bools are rejected)."""

CategoryList = Annotated[list[Category], Field(min_length=1)]
"""Non-empty list of catalog categories. `None` is used for "all categories"."""

Weekday = Annotated[int, Field(strict=True, ge=0, le=6)]
"""0 = Monday ... 6 = Sunday (same as `datetime.weekday()`)."""


class RuleType(StrEnum):
    MAX_AMOUNT = "max_amount"
    PROHIBITED_CATEGORY = "prohibited_category"
    PRE_APPROVAL_THRESHOLD = "pre_approval_threshold"
    PERIOD_LIMIT = "period_limit"
    TIME_RESTRICTION = "time_restriction"


class Period(StrEnum):
    """Accumulation period for `period_limit`, computed in company time."""

    MONTH = "month"
    WEEK = "week"


def _reject_duplicates[T](values: list[T] | None) -> list[T] | None:
    if values is not None and len(set(values)) != len(values):
        raise ValueError("duplicate values are not allowed")
    return values


class _Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def explicit_categories(self) -> frozenset[Category]:
        """Categories this rule names explicitly (empty when it applies to all)."""
        raise NotImplementedError


class _SingleCategoryParams(_Params):
    category: Category

    def explicit_categories(self) -> frozenset[Category]:
        return frozenset({self.category})


class _OptionalCategoriesParams(_Params):
    categories: CategoryList | None = None

    @field_validator("categories")
    @classmethod
    def _unique_categories(cls, value: list[Category] | None) -> list[Category] | None:
        return _reject_duplicates(value)

    def explicit_categories(self) -> frozenset[Category]:
        return frozenset(self.categories or ())

    def applies_to(self, category: Category) -> bool:
        """`categories = None` means the rule applies to every category."""
        return self.categories is None or category in self.categories


class MaxAmountParams(_SingleCategoryParams):
    """`amount > amount_minor` in `category` -> rejected. Equal passes."""

    type: Literal["max_amount"] = "max_amount"
    amount_minor: PositiveMinor


class ProhibitedCategoryParams(_SingleCategoryParams):
    """Any expense in `category` -> rejected."""

    type: Literal["prohibited_category"] = "prohibited_category"


class PreApprovalThresholdParams(_OptionalCategoriesParams):
    """`amount > amount_minor` without a pre-approval id -> needs_approval.

    `categories = None` means every category.
    """

    type: Literal["pre_approval_threshold"] = "pre_approval_threshold"
    amount_minor: PositiveMinor


class PeriodLimitParams(_SingleCategoryParams):
    """Per-employee cap on the sum of `category` expenses per `period` (SPEC §4.3)."""

    type: Literal["period_limit"] = "period_limit"
    amount_minor: PositiveMinor
    period: Period


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class TimeWindow(BaseModel):
    """Allowed local time-of-day window, `start` inclusive and `end` exclusive.

    If `start > end` the window wraps midnight (e.g. 22:00-06:00).
    """

    # SPEC-QUESTION: the spec does not say whether `end` is inclusive or whether
    # windows may wrap midnight. We take end as exclusive (the stricter reading)
    # and allow wrapping; start == end is rejected as ambiguous.

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: Annotated[str, Field(pattern=_HHMM)]
    end: Annotated[str, Field(pattern=_HHMM)]

    @model_validator(mode="after")
    def _not_empty(self) -> "TimeWindow":
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self

    def contains(self, moment: time) -> bool:
        """True if the local wall-clock `moment` falls inside the window."""
        start, end = time.fromisoformat(self.start), time.fromisoformat(self.end)
        moment = moment.replace(second=0, microsecond=0, tzinfo=None)
        if start < end:
            return start <= moment < end
        return moment >= start or moment < end


class TimeRestrictionParams(_OptionalCategoriesParams):
    """Expenses outside the allowed weekdays/hours (company tz) are rejected.

    With `justification_allows_review` and a non-empty justification they become
    needs_approval instead. `categories = None` means every category;
    `allowed_hours = None` means any time on an allowed day.
    """

    type: Literal["time_restriction"] = "time_restriction"
    allowed_weekdays: Annotated[list[Weekday], Field(min_length=1)]
    allowed_hours: TimeWindow | None = None
    justification_allows_review: bool = False

    @field_validator("allowed_weekdays")
    @classmethod
    def _unique_weekdays(cls, value: list[int]) -> list[int]:
        return _reject_duplicates(value)


RuleParams = Annotated[
    MaxAmountParams
    | ProhibitedCategoryParams
    | PreApprovalThresholdParams
    | PeriodLimitParams
    | TimeRestrictionParams,
    Field(discriminator="type"),
]
"""Typed params of any rule; validate with `TypeAdapter(RuleParams)` or as a field."""


class PolicyRule(BaseModel):
    """An approved rule of an active policy version, as consumed by the engine."""

    model_config = ConfigDict(frozen=True)

    id: int
    clause: Annotated[str, Field(min_length=1)]
    """Literal quote from the policy text that this rule encodes."""
    params: RuleParams

    @property
    def type(self) -> RuleType:
        return RuleType(self.params.type)

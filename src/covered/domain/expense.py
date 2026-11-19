"""The expense as submitted for evaluation (before it is stored)."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from covered.domain.categories import Category
from covered.domain.money import CURRENCY
from covered.domain.rules import PositiveMinor


class ExpenseInput(BaseModel):
    """An expense to evaluate. `occurred_at` must be timezone-aware.

    Unknown categories and currencies other than the company currency are
    validation errors (Pydantic `ValidationError`, rendered as HTTP 422).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    employee_id: Annotated[str, Field(min_length=1)]
    amount_minor: PositiveMinor
    currency: str = CURRENCY
    category: Category
    merchant: str | None = None
    occurred_at: AwareDatetime
    justification: str | None = None
    pre_approval_id: str | None = None

    @field_validator("currency")
    @classmethod
    def _company_currency(cls, value: str) -> str:
        if value != CURRENCY:
            raise ValueError(
                f"unsupported currency {value!r}: only {CURRENCY} is supported"
            )
        return value

    @property
    def has_justification(self) -> bool:
        return bool(self.justification and self.justification.strip())

    @property
    def has_pre_approval(self) -> bool:
        return bool(self.pre_approval_id and self.pre_approval_id.strip())

"""Types of an intake: the provider contract and the validated draft.

The draft is only a suggestion for the employee's check form. It has no
outcome, no rule and no decision: coverage is decided later by the engine,
on whatever the employee confirms.
"""

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from covered.domain import Category


class IntakeMeta(BaseModel):
    """What one provider call cost. Fields are None when unknown."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    cost_usd: Decimal | None = None


class IntakeReply(BaseModel):
    """Raw provider output (JSON text, not yet validated) plus its metadata."""

    model_config = ConfigDict(frozen=True)

    payload: str
    meta: IntakeMeta


class IntakeProviderError(Exception):
    """The provider produced nothing usable (API error, refusal, truncation...)."""

    def __init__(self, message: str, meta: IntakeMeta) -> None:
        super().__init__(message)
        self.message = message
        self.meta = meta


class IntakeProvider(Protocol):
    """Anything that turns one sentence into an `IntakePayload` JSON payload."""

    name: str

    def read(self, text: str) -> IntakeReply:
        """Return the raw JSON payload, or raise `IntakeProviderError`."""
        ...


class IntakeFlag(BaseModel):
    """Something the employee must look at before checking the expense."""

    model_config = ConfigDict(frozen=True)

    code: str
    field: str | None = None
    message: str


class ExpenseDraft(BaseModel):
    """Prefill for the check form. Every field may be missing; nothing is invented."""

    model_config = ConfigDict(frozen=True)

    category: Category | None = None
    amount_minor: int | None = None
    currency: str | None = None
    occurred_at: datetime | None = None
    merchant: str | None = None
    description: str | None = None
    justification: str | None = None


class IntakeResult(BaseModel):
    """`POST /expenses/parse` response: a draft, what is missing, what to review."""

    model_config = ConfigDict(frozen=True)

    draft: ExpenseDraft
    missing: tuple[str, ...]
    flags: tuple[IntakeFlag, ...]
    provider: str
    model: str
    meta: IntakeMeta

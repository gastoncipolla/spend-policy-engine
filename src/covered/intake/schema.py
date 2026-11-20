"""What an intake provider must return: `IntakePayload`, a literal reading of the text.

The provider only *reads* the sentence. It copies the amount exactly as written,
names the currency, and describes the date as a small structure (relative days,
previous weekday, calendar date) instead of computing it. Turning that into
minor units and a timezone-aware datetime is deterministic code
(`covered.intake.validation`), so it can be tested and never hallucinated.

Field order matters for structured outputs: properties are generated in schema
order, so the fields that decide how the rest is read (`expense_count`,
`category`, `date_kind`) come before the fields that depend on them.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DateKind(StrEnum):
    NONE = "none"
    """The text gives no date."""
    RELATIVE_DAYS = "relative_days"
    """today (0), yesterday (-1), "3 days ago" (-3), tomorrow (+1)..."""
    PREVIOUS_WEEKDAY = "previous_weekday"
    """"el sábado", "last Tuesday": the most recent such weekday before today."""
    CALENDAR_DATE = "calendar_date"
    """"14/11", "Nov 14 2026": day + month, year optional."""


class IntakePayload(BaseModel):
    """Structured output of an intake provider. Every field is required (nullable)."""

    model_config = ConfigDict(extra="forbid")

    expense_count: int
    """How many distinct expenses the text describes (0, 1, 2...)."""
    category: str | None
    """A catalog code, or null when no category clearly applies."""
    amount_text: str | None
    """The number exactly as written in the text ("1.234,50", "45"), no symbols."""
    currency: str | None
    """ISO 4217 code only when the text names it (USD, EUR, ARS...); null otherwise."""
    date_kind: DateKind
    offset_days: int | None
    """For relative_days: 0 today, -1 yesterday, +1 tomorrow."""
    weekday: int | None
    """For previous_weekday: 0=Monday..6=Sunday."""
    day: int | None
    """For calendar_date."""
    month: int | None
    """For calendar_date."""
    year: int | None
    """For calendar_date, only if the text states it."""
    date_text: str | None
    """The literal words of the text that state the date ("el viernes pasado")."""
    time: str | None
    """"HH:MM" (24h) only if the text states a time."""
    merchant: str | None
    """Merchant name exactly as written, if any."""
    description: str | None
    """A short neutral description of the expense (under 12 words)."""
    justification: str | None
    """The business reason only if the text states one, else null."""

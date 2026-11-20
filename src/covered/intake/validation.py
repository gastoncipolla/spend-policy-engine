"""Deterministic validation of a provider payload (never trust the provider).

- category must be in the closed catalog, else dropped and flagged;
- the amount must literally appear in the text and parse with the money rules;
- only the company currency; anything else is a field error and no amount;
- the date is resolved in code against `now` in the company timezone; future
  dates are flagged; a stated date must appear in the text;
- the merchant must appear in the text;
- more than one expense in the text is flagged;
- every required field that is not filled is listed in `missing`, never invented.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from covered.domain import Category
from covered.domain.errors import InvalidAmountError
from covered.domain.money import CURRENCY
from covered.intake.amounts import AmountNotInText, literal_amount
from covered.intake.dates import local_moment, parse_clock, resolve_day
from covered.intake.result import ExpenseDraft, IntakeFlag
from covered.intake.schema import DateKind, IntakePayload

REQUIRED_FIELDS = ("amount", "category", "occurred_at")
MAX_FREE_TEXT = 200
"""Longest merchant / description / justification kept from the provider."""


class PayloadInvalid(ValueError):
    """The provider's JSON does not match `IntakePayload`."""


def parse_payload(payload: str) -> IntakePayload:
    try:
        return IntakePayload.model_validate(json.loads(payload))
    except (ValueError, ValidationError) as exc:
        raise PayloadInvalid(str(exc)) from exc


def validate_payload(
    payload: IntakePayload, text: str, now: datetime, tz: ZoneInfo
) -> tuple[ExpenseDraft, tuple[str, ...], tuple[IntakeFlag, ...]]:
    """Return (draft, missing, flags) for the employee's `text`."""
    flags: list[IntakeFlag] = []
    category = _category(payload, flags)
    amount, currency = _amount(payload, text, flags)
    occurred_at = _occurred_at(payload, text, now, tz, flags)
    if payload.expense_count > 1:
        flags.append(
            IntakeFlag(
                code="multiple_expenses",
                message=f"The text seems to describe {payload.expense_count} "
                "expenses; check them one at a time.",
            )
        )
    draft = ExpenseDraft(
        category=category,
        amount_minor=amount,
        currency=currency,
        occurred_at=occurred_at,
        merchant=_literal(payload.merchant, text, "merchant", flags),
        description=_clip(payload.description),
        justification=_clip(payload.justification),
    )
    filled = {
        "amount": amount is not None,
        "category": category is not None,
        "occurred_at": occurred_at is not None,
    }
    missing = tuple(name for name in REQUIRED_FIELDS if not filled[name])
    return draft, missing, tuple(flags)


def _category(payload: IntakePayload, flags: list[IntakeFlag]) -> Category | None:
    if payload.category is None:
        return None
    try:
        return Category(payload.category)
    except ValueError:
        flags.append(
            IntakeFlag(
                code="unknown_category",
                field="category",
                message=f"{payload.category!r} is not a known category; pick one.",
            )
        )
        return None


def _amount(
    payload: IntakePayload, text: str, flags: list[IntakeFlag]
) -> tuple[int | None, str | None]:
    currency = (payload.currency or "").strip().upper() or None
    if currency is not None and currency != CURRENCY:
        flags.append(
            IntakeFlag(
                code="unsupported_currency",
                field="currency",
                message=f"Unsupported currency {currency!r}: only {CURRENCY} is "
                "supported. Enter the amount in USD.",
            )
        )
        return None, currency
    if payload.amount_text is None:
        return None, currency
    try:
        amount = literal_amount(payload.amount_text, text)
    except AmountNotInText:
        flags.append(
            IntakeFlag(
                code="amount_not_in_text",
                field="amount",
                message="The suggested amount is not written in the text; "
                "it was discarded.",
            )
        )
        return None, currency
    except (InvalidAmountError, ValueError):
        flags.append(
            IntakeFlag(
                code="invalid_amount",
                field="amount",
                message=f"{payload.amount_text!r} is not a valid amount.",
            )
        )
        return None, currency
    if currency is None:
        flags.append(
            IntakeFlag(
                code="currency_assumed",
                field="currency",
                message=f"No currency written; assumed {CURRENCY}. Check it.",
            )
        )
    return amount, CURRENCY


def _occurred_at(
    payload: IntakePayload,
    text: str,
    now: datetime,
    tz: ZoneInfo,
    flags: list[IntakeFlag],
) -> datetime | None:
    if payload.date_kind == DateKind.NONE:
        return None
    if _literal(payload.date_text, text, "occurred_at", flags) is None:
        return None
    day = resolve_day(payload, now.astimezone(tz).date())
    if day is None:
        flags.append(
            IntakeFlag(
                code="invalid_date",
                field="occurred_at",
                message=f"Could not work out the date from {payload.date_text!r}.",
            )
        )
        return None
    clock = parse_clock(payload.time)
    local_now = now.astimezone(tz).replace(second=0, microsecond=0)
    moment = local_moment(day, clock, tz)
    if clock is None and day == local_now.date():
        moment = min(moment, local_now)  # "today" with no time: not later than now
    if clock is None:
        flags.append(
            IntakeFlag(
                code="time_not_stated",
                field="occurred_at",
                message="No time in the text; noon was used. Time rules may "
                "depend on it.",
            )
        )
    if moment > now:
        flags.append(
            IntakeFlag(
                code="future_date",
                field="occurred_at",
                message="This date is in the future.",
            )
        )
    return moment


def _literal(
    value: str | None, text: str, field: str, flags: list[IntakeFlag]
) -> str | None:
    """`value` if it appears in `text` (case-insensitive), else None + a flag."""
    if value is None or not value.strip():
        return None
    if value.strip().casefold() not in text.casefold():
        flags.append(
            IntakeFlag(
                code="not_in_text",
                field=field,
                message=f"{value!r} is not written in the text; it was discarded.",
            )
        )
        return None
    return _clip(value)


def _clip(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()[:MAX_FREE_TEXT]

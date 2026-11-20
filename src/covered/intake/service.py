"""Use case: turn an employee's sentence into a reviewed draft. Stores nothing.

The result never contains a decision. The API, the page and the CLI show the
draft; the employee confirms it in the check form, and only then does the
deterministic engine evaluate it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from covered.domain.errors import InvalidInputError
from covered.intake.result import (
    ExpenseDraft,
    IntakeFlag,
    IntakeProvider,
    IntakeProviderError,
    IntakeResult,
)
from covered.intake.validation import (
    REQUIRED_FIELDS,
    PayloadInvalid,
    parse_payload,
    validate_payload,
)
from covered.services.events import log_event

MAX_TEXT_LENGTH = 500
"""Longest accepted sentence: an expense note, not a document."""


def parse_expense_text(
    text: str, provider: IntakeProvider, *, now: datetime, tz: ZoneInfo
) -> IntakeResult:
    """Read `text` with `provider` and validate the draft against `now` in `tz`.

    Raises `InvalidInputError` for empty or too long text. A provider failure is
    not an error for the employee: it returns an empty draft with a flag, so the
    form can still be filled by hand.
    """
    text = text.strip()
    if not text:
        raise InvalidInputError("describe the expense in a sentence")
    if len(text) > MAX_TEXT_LENGTH:
        raise InvalidInputError(
            f"the description is too long (max {MAX_TEXT_LENGTH} characters)"
        )
    try:
        reply = provider.read(text)
        meta = reply.meta
        draft, missing, flags = validate_payload(
            parse_payload(reply.payload), text, now, tz
        )
    except (IntakeProviderError, PayloadInvalid) as exc:
        meta = exc.meta if isinstance(exc, IntakeProviderError) else reply.meta
        draft, missing = ExpenseDraft(), REQUIRED_FIELDS
        flags = (
            IntakeFlag(
                code="provider_error",
                message="Could not read the sentence; fill in the form by hand.",
            ),
        )
    log_event(
        "expense_parse",
        provider=meta.provider,
        model=meta.model,
        prompt_version=meta.prompt_version,
        input_tokens=meta.input_tokens,
        output_tokens=meta.output_tokens,
        latency_ms=meta.latency_ms,
        cost_usd=meta.cost_usd,
        missing=list(missing),
        flags=[flag.code for flag in flags],
    )
    return IntakeResult(
        draft=draft,
        missing=missing,
        flags=flags,
        provider=meta.provider,
        model=meta.model,
        meta=meta,
    )

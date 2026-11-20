"""Natural-language expense intake ("Ask Covered").

The LLM only turns a sentence into a draft expense; deterministic code
validates the draft, and the engine decides coverage on what the employee
confirms. Entry point: `parse_expense_text(text, get_intake_provider(), ...)`.
"""

from covered.intake.anthropic_provider import AnthropicIntakeProvider
from covered.intake.factory import get_intake_provider
from covered.intake.mock_provider import MockIntakeProvider
from covered.intake.prompt import PROMPT_VERSION
from covered.intake.result import (
    ExpenseDraft,
    IntakeFlag,
    IntakeMeta,
    IntakeProvider,
    IntakeProviderError,
    IntakeReply,
    IntakeResult,
)
from covered.intake.service import MAX_TEXT_LENGTH, parse_expense_text

__all__ = [
    "MAX_TEXT_LENGTH",
    "PROMPT_VERSION",
    "AnthropicIntakeProvider",
    "ExpenseDraft",
    "IntakeFlag",
    "IntakeMeta",
    "IntakeProvider",
    "IntakeProviderError",
    "IntakeReply",
    "IntakeResult",
    "MockIntakeProvider",
    "get_intake_provider",
    "parse_expense_text",
]

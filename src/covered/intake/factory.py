"""Pick the intake provider from the environment (same switch as the compiler).

- `COVERED_PROVIDER=mock` -> MockIntakeProvider.
- `COVERED_PROVIDER=anthropic` -> AnthropicIntakeProvider (requires `ANTHROPIC_API_KEY`).
- unset -> Anthropic if `ANTHROPIC_API_KEY` is set, else mock.

The model is `COVERED_INTAKE_MODEL` (default `claude-haiku-5-5`), separate from
the compiler's `COVERED_MODEL`: reading a sentence is a much smaller task.
"""

import os
from collections.abc import Mapping

from covered.domain.errors import InvalidInputError
from covered.intake.anthropic_provider import MODEL_ENV, AnthropicIntakeProvider
from covered.intake.mock_provider import MockIntakeProvider
from covered.intake.result import IntakeProvider


def get_intake_provider(env: Mapping[str, str] | None = None) -> IntakeProvider:
    env = os.environ if env is None else env
    choice = env.get("COVERED_PROVIDER", "").strip().lower()
    has_key = bool(env.get("ANTHROPIC_API_KEY", "").strip())

    if choice == "mock" or (not choice and not has_key):
        return MockIntakeProvider()
    if choice in ("anthropic", ""):
        if not has_key:
            raise InvalidInputError(
                "COVERED_PROVIDER=anthropic requires ANTHROPIC_API_KEY"
            )
        return AnthropicIntakeProvider(
            model=env.get(MODEL_ENV) or None, api_key=env["ANTHROPIC_API_KEY"]
        )
    raise InvalidInputError(f"unknown COVERED_PROVIDER: {choice!r}")

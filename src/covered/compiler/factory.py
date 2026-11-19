"""Pick the compilation provider from the environment (SPEC §5.1).

- `COVERED_PROVIDER=mock` -> MockProvider.
- `COVERED_PROVIDER=anthropic` -> AnthropicProvider (requires `ANTHROPIC_API_KEY`).
- unset -> AnthropicProvider if `ANTHROPIC_API_KEY` is set, else MockProvider.
"""

import os
from collections.abc import Mapping

from covered.compiler.anthropic_provider import AnthropicProvider
from covered.compiler.mock_provider import MockProvider
from covered.compiler.result import Provider
from covered.domain.errors import InvalidInputError


def get_provider(env: Mapping[str, str] | None = None) -> Provider:
    env = os.environ if env is None else env
    choice = env.get("COVERED_PROVIDER", "").strip().lower()
    has_key = bool(env.get("ANTHROPIC_API_KEY", "").strip())

    if choice == "mock" or (not choice and not has_key):
        return MockProvider()
    if choice in ("anthropic", ""):
        if not has_key:
            raise InvalidInputError(
                "COVERED_PROVIDER=anthropic requires ANTHROPIC_API_KEY"
            )
        return AnthropicProvider(
            model=env.get("COVERED_MODEL") or None, api_key=env["ANTHROPIC_API_KEY"]
        )
    raise InvalidInputError(f"unknown COVERED_PROVIDER: {choice!r}")

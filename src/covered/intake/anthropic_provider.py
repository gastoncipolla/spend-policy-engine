"""Real intake provider: Anthropic Messages API with structured outputs.

Same SDK usage as the compiler (`covered.compiler.anthropic_provider`): the JSON
schema comes from `IntakePayload` via `transform_schema` and is sent as
`output_config.format`; transport retries are the SDK's job. Anything without
usable output raises `IntakeProviderError`; the caller turns that into an empty
draft, so the employee can still fill the form by hand.
"""

import os
import time
from decimal import Decimal
from typing import Any

import anthropic

from covered.domain import Category
from covered.intake.prompt import PROMPT_VERSION, SYSTEM_PROMPT, user_message
from covered.intake.result import IntakeMeta, IntakeProviderError, IntakeReply
from covered.intake.schema import IntakePayload

DEFAULT_MODEL = "claude-haiku-5-5"
MODEL_ENV = "COVERED_INTAKE_MODEL"
MAX_RETRIES = 2
TIMEOUT_SECONDS = 20.0
"""An employee is waiting on the page: fail fast and let them type instead."""
MAX_TOKENS = 4000
EFFORT = "low"
"""Reading one sentence needs little reasoning; low effort keeps latency down."""

PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal(2), Decimal(10)),
}
"""USD per million (input, output) tokens. Unknown models get `cost_usd=None`."""


def output_schema() -> dict[str, Any]:
    """JSON schema for structured outputs, with `category` limited to the catalog.

    The Pydantic model keeps `category` a plain string so that an unknown value
    reaches validation (and is flagged) instead of failing the whole payload;
    the schema sent to the model constrains it to the catalog codes.
    """
    schema = anthropic.transform_schema(IntakePayload)
    codes = [code.value for code in Category]
    category = schema["properties"]["category"]
    for branch in category.get("anyOf", [category]):
        if branch.get("type") == "string":
            branch["enum"] = codes
    return schema


class AnthropicIntakeProvider:
    name = "anthropic"

    def __init__(
        self, client: Any = None, model: str | None = None, api_key: str | None = None
    ) -> None:
        """`client` is injectable so tests can pass a fake; never call the API in tests."""
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self.client = client or anthropic.Anthropic(
            api_key=api_key, max_retries=MAX_RETRIES, timeout=TIMEOUT_SECONDS
        )

    def read(self, text: str) -> IntakeReply:
        started = time.perf_counter()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message(text)}],
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": output_schema()},
                },
            )
        except anthropic.APIStatusError as error:
            raise IntakeProviderError(
                f"api_error: HTTP {error.status_code}", self._meta(started)
            ) from error
        except anthropic.APIConnectionError as error:
            raise IntakeProviderError(
                "api_connection_error", self._meta(started)
            ) from error

        meta = self._meta(started, response.usage)
        if response.stop_reason == "refusal":
            raise IntakeProviderError("refusal", meta)
        if response.stop_reason == "max_tokens":
            raise IntakeProviderError("max_tokens", meta)
        payload = next(
            (block.text for block in response.content if block.type == "text"), None
        )
        if payload is None:
            raise IntakeProviderError("no text output", meta)
        return IntakeReply(payload=payload, meta=meta)

    def _meta(self, started: float, usage: Any = None) -> IntakeMeta:
        input_tokens = usage.input_tokens if usage else None
        output_tokens = usage.output_tokens if usage else None
        return IntakeMeta(
            provider=self.name,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
            cost_usd=cost_usd(self.model, input_tokens, output_tokens),
        )


def cost_usd(
    model: str, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    input_price, output_price = prices
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000

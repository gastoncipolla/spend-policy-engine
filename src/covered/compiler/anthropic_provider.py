"""Real provider: Anthropic Messages API with structured outputs (SPEC §5.1-5.2).

- The JSON schema comes from `CompilationResult` via the SDK's `transform_schema`
  and is sent as `output_config.format`.
- Transport retries are the SDK's job (`max_retries=3`, `timeout=60s`): there is
  no retry loop here, which would multiply attempts.
- Anything that leaves us without usable output (API error after the SDK gave
  up, refusal, max_tokens, no text) raises `ProviderError`. Schema validation of
  the text happens in `compile_text`, the same path as the mock provider.
"""

import os
import time
from decimal import Decimal
from typing import Any

import anthropic

from covered.compiler.prompt import PROMPT_VERSION, SYSTEM_PROMPT, user_message
from covered.compiler.result import CompileMeta, ProviderError, ProviderReply
from covered.compiler.schema import CompilationResult

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 60.0
MAX_TOKENS = 16000

PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-5-5": (Decimal(2), Decimal(10)),
}
"""USD per million (input, output) tokens. Unknown models get `cost_usd=None`."""


def output_schema() -> dict[str, Any]:
    """JSON schema for structured outputs, with `type` required and first in every rule.

    Structured outputs generate properties in schema order. If `type` comes last
    (or is optional because it has a default), the model must commit to a rule
    variant before naming it, and in practice it mixed variants: a meals limit
    came back as a pre-approval threshold. Naming the type first fixes that.
    """
    schema = anthropic.transform_schema(CompilationResult)
    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties", {})
        if "type" not in properties or "const" not in properties["type"]:
            continue
        definition["properties"] = {
            "type": properties["type"],
            **{name: value for name, value in properties.items() if name != "type"},
        }
        required = [name for name in definition.get("required", []) if name != "type"]
        definition["required"] = ["type", *required]
    return schema


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, client: Any = None, model: str | None = None, api_key: str | None = None
    ) -> None:
        """`client` is injectable so tests can pass a fake; never call the API in tests.

        Without `api_key` the SDK reads `ANTHROPIC_API_KEY` from the environment.
        """
        self.model = model or os.environ.get("COVERED_MODEL", DEFAULT_MODEL)
        self.client = client or anthropic.Anthropic(
            api_key=api_key, max_retries=MAX_RETRIES, timeout=TIMEOUT_SECONDS
        )

    def propose(self, text: str) -> ProviderReply:
        started = time.perf_counter()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message(text)}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": output_schema(),
                    }
                },
            )
        except anthropic.APIStatusError as error:
            raise ProviderError(
                f"api_error: HTTP {error.status_code}: {error.message}",
                self._meta(started),
            ) from error
        except anthropic.APIConnectionError as error:
            # Includes APITimeoutError; the SDK already retried it.
            raise ProviderError(
                f"api_connection_error: {error.message}", self._meta(started)
            ) from error

        meta = self._meta(started, response.usage)
        if response.stop_reason == "refusal":
            raise ProviderError("refusal: the model declined to compile", meta)
        if response.stop_reason == "max_tokens":
            raise ProviderError("max_tokens: the output was truncated", meta)
        payload = next(
            (block.text for block in response.content if block.type == "text"), None
        )
        if payload is None:
            raise ProviderError("schema_invalid: no text output", meta)
        return ProviderReply(payload=payload, meta=meta)

    def _meta(self, started: float, usage: Any = None) -> CompileMeta:
        input_tokens = usage.input_tokens if usage else None
        output_tokens = usage.output_tokens if usage else None
        return CompileMeta(
            provider=self.name,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
            cost_usd=self._cost(input_tokens, output_tokens),
        )

    def _cost(
        self, input_tokens: int | None, output_tokens: int | None
    ) -> Decimal | None:
        prices = PRICES_PER_MTOK.get(self.model)
        if prices is None or input_tokens is None or output_tokens is None:
            return None
        input_price, output_price = prices
        return (input_tokens * input_price + output_tokens * output_price) / 1_000_000

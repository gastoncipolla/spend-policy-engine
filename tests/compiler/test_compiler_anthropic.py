"""AnthropicProvider with a fake client (never a real API call) and get_provider."""

import json
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from compiler_builders import POLICY, max_meals

from covered.compiler import (
    PROMPT_VERSION,
    AnthropicProvider,
    MockProvider,
    compile_text,
    get_provider,
)
from covered.compiler.prompt import SYSTEM_PROMPT
from covered.domain.errors import InvalidInputError

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
VALID = json.dumps({"rules": [max_meals()], "uncompilable": []})


def response(text=VALID, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
    )


class FakeClient:
    """Stands in for `anthropic.Anthropic`: records calls, returns or raises."""

    def __init__(self, result):
        self.result = result
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def compile_with(result, model="claude-sonnet-5-5"):
    client = FakeClient(result)
    outcome = compile_text(POLICY, AnthropicProvider(client=client, model=model))
    return outcome, client


def test_success_sends_structured_output_request_and_reports_meta():
    outcome, client = compile_with(response())
    assert outcome.ok
    assert outcome.rules[0].params.amount_minor == 8000

    [call] = client.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "rules" in call["output_config"]["format"]["schema"]["properties"]
    assert f"<policy>\n{POLICY}\n</policy>" in call["messages"][0]["content"]
    assert "data" in call["system"]

    meta = outcome.meta
    assert (meta.provider, meta.prompt_version) == ("anthropic", PROMPT_VERSION)
    assert (meta.input_tokens, meta.output_tokens) == (1000, 500)
    assert meta.cost_usd == Decimal("0.007")  # 1000 * $2/M + 500 * $10/M
    assert meta.latency_ms is not None


def test_haiku_has_a_price():
    outcome, _ = compile_with(response(), model="claude-haiku-5-5")
    assert outcome.meta.cost_usd == Decimal("0.00035")  # 1000 * $0.10/M + 500 * $0.50/M


def test_default_model_is_haiku_and_overridable(monkeypatch):
    monkeypatch.delenv("COVERED_MODEL", raising=False)
    assert AnthropicProvider(client=FakeClient(response())).model == "claude-haiku-5-5"
    monkeypatch.setenv("COVERED_MODEL", "claude-sonnet-5-5")
    assert AnthropicProvider(client=FakeClient(response())).model == "claude-sonnet-5-5"


def test_prompt_marks_per_unit_limits_as_uncompilable():
    prompt = " ".join(SYSTEM_PROMPT.split())
    assert "per night, per person" in prompt
    assert "cannot be expressed as max_amount" in prompt


def test_unknown_model_has_no_cost():
    outcome, _ = compile_with(response(), model="some-other-model")
    assert outcome.meta.cost_usd is None


def test_refusal_is_a_failure():
    outcome, _ = compile_with(response(text="", stop_reason="refusal"))
    assert not outcome.ok
    assert outcome.error.startswith("refusal")
    assert outcome.meta.input_tokens == 1000


def test_max_tokens_is_a_failure():
    outcome, _ = compile_with(response(text='{"rules": [', stop_reason="max_tokens"))
    assert not outcome.ok
    assert outcome.error.startswith("max_tokens")


def test_schema_invalid_text_is_a_failure():
    outcome, _ = compile_with(response(text='{"rules": "nope"}'))
    assert not outcome.ok
    assert outcome.error.startswith("schema_invalid")


def test_no_text_block_is_a_failure():
    reply = response()
    reply.content = []
    outcome, _ = compile_with(reply)
    assert not outcome.ok


def test_non_retryable_api_error_is_a_failure():
    error = anthropic.BadRequestError(
        "invalid schema", response=httpx2.Response(400, request=REQUEST), body=None
    )
    outcome, client = compile_with(error)
    assert not outcome.ok
    assert outcome.error == "api_error: HTTP 400: invalid schema"
    assert len(client.calls) == 1  # no application-level retry
    assert outcome.meta.input_tokens is None


def test_connection_error_after_sdk_retries_is_a_failure():
    outcome, client = compile_with(anthropic.APIConnectionError(request=REQUEST))
    assert not outcome.ok
    assert outcome.error.startswith("api_connection_error")
    assert len(client.calls) == 1


def test_real_client_is_configured_with_sdk_retries_and_timeout():
    provider = AnthropicProvider(api_key="test-key-not-used")
    assert provider.client.max_retries == 3
    assert provider.client.timeout == 60.0


def test_get_provider_defaults_to_mock_without_key():
    assert isinstance(get_provider({}), MockProvider)
    assert isinstance(
        get_provider({"COVERED_PROVIDER": "mock", "ANTHROPIC_API_KEY": "k"}),
        MockProvider,
    )


def test_get_provider_uses_anthropic_with_key():
    provider = get_provider({"ANTHROPIC_API_KEY": "k", "COVERED_MODEL": "m"})
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "m"


def test_get_provider_rejects_bad_configuration():
    with pytest.raises(InvalidInputError):
        get_provider({"COVERED_PROVIDER": "anthropic"})
    with pytest.raises(InvalidInputError):
        get_provider({"COVERED_PROVIDER": "openai"})


def test_output_schema_names_the_rule_type_first_and_requires_it():
    # Regression: with `type` optional and last, the real model mixed rule variants.
    from covered.compiler.anthropic_provider import output_schema

    variants = [
        definition
        for definition in output_schema()["$defs"].values()
        if "const" in definition.get("properties", {}).get("type", {})
    ]
    assert len(variants) == 5
    for definition in variants:
        assert next(iter(definition["properties"])) == "type"
        assert definition["required"][0] == "type"

"""The adapter from `compile_text` + provider to the services' `Compiler`."""

from decimal import Decimal

from covered.compiler import CompileMeta, MockProvider, ValidatedUncompilable
from covered.compiler.result import CompileFailure, CompileSuccess
from covered.domain import UncompilableEffect
from covered.services.compilation import CompilationFailure, CompilationSuccess
from covered.services.provider_compiler import (
    ProviderCompiler,
    default_compiler,
    to_services_outcome,
)

META = CompileMeta(
    provider="fake", model="m", prompt_version="p", cost_usd=Decimal("0.01")
)


def test_failure_keeps_error_and_json_meta():
    outcome = to_services_outcome(CompileFailure(error="refusal", meta=META))
    assert isinstance(outcome, CompilationFailure)
    assert outcome.error == "refusal"
    assert outcome.meta["cost_usd"] == "0.01"  # Decimal serialized, never float


def test_success_maps_uncompilable_categories_to_strings():
    item = ValidatedUncompilable(
        clause="Prefer partner hotels.",
        reason="vague",
        categories=("lodging",),
        effect=UncompilableEffect.INFORMATIONAL,
    )
    outcome = to_services_outcome(
        CompileSuccess(rules=(), uncompilable=(item,), meta=META)
    )
    assert isinstance(outcome, CompilationSuccess)
    assert outcome.uncompilable[0].categories == ["lodging"]


def test_unknown_text_with_mock_fails_cleanly():
    outcome = ProviderCompiler(MockProvider())("not a sample policy")
    assert isinstance(outcome, CompilationFailure)
    assert "mock mode only supports the sample policies" in outcome.error


def test_default_compiler_without_key_is_the_mock():
    assert default_compiler({}).provider_name == "mock"
    assert default_compiler({"ANTHROPIC_API_KEY": "k"}).provider_name == "anthropic"

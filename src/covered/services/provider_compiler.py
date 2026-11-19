"""Adapter: the compiler package (`compile_text` + a provider) as a services `Compiler`.

The services layer only knows "text in, CompilationSuccess | CompilationFailure out";
this module translates the compiler's own result types into those.
"""

from collections.abc import Mapping

from covered.compiler import CompileOutcome, Provider, compile_text, get_provider
from covered.services.compilation import (
    CompilationFailure,
    CompilationOutcome,
    CompilationSuccess,
    ProposedRule,
    ProposedUncompilable,
)


class ProviderCompiler:
    """Callable `Compiler` backed by one provider (mock or Anthropic)."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def __call__(self, text: str) -> CompilationOutcome:
        return to_services_outcome(compile_text(text, self.provider))


def to_services_outcome(outcome: CompileOutcome) -> CompilationOutcome:
    meta = outcome.meta.model_dump(mode="json")  # Decimal cost -> string
    if not outcome.ok:
        return CompilationFailure(error=outcome.error, meta=meta)
    return CompilationSuccess(
        rules=[
            ProposedRule(params=rule.params, clause=rule.clause, flags=rule.flags)
            for rule in outcome.rules
        ],
        uncompilable=[
            ProposedUncompilable(
                clause=item.clause,
                reason=item.reason,
                categories=[str(category) for category in item.categories],
                effect=item.effect,
            )
            for item in outcome.uncompilable
        ],
        meta=meta,
    )


def default_compiler(env: Mapping[str, str] | None = None) -> ProviderCompiler:
    """The compiler chosen by the environment (SPEC §5.1): Anthropic or mock."""
    return ProviderCompiler(get_provider(env))

"""Top-level compilation: provider call + schema + deterministic validation."""

from pydantic import ValidationError

from covered.compiler.result import (
    CompileFailure,
    CompileOutcome,
    CompileSuccess,
    Provider,
    ProviderError,
)
from covered.compiler.schema import CompilationResult
from covered.compiler.validation import validate_result


def compile_text(text: str, provider: Provider) -> CompileOutcome:
    """Propose rules for `text`. Never raises for provider or schema problems.

    Returns `CompileSuccess` (rules + uncompilable clauses to store as
    `proposed`) or `CompileFailure` (store nothing, keep `error`). Both carry the
    provider metadata.
    """
    try:
        reply = provider.propose(text)
    except ProviderError as error:
        return CompileFailure(error=error.message, meta=error.meta)

    try:
        result = CompilationResult.model_validate_json(reply.payload)
    except ValidationError as error:
        return CompileFailure(
            error=f"schema_invalid: {_summarize(error)}", meta=reply.meta
        )

    rules, uncompilable = validate_result(result, text)
    return CompileSuccess(
        rules=tuple(rules), uncompilable=tuple(uncompilable), meta=reply.meta
    )


def _summarize(error: ValidationError, limit: int = 3) -> str:
    """Short, human-readable list of the first validation problems."""
    problems = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()[:limit]
    ]
    more = error.error_count() - len(problems)
    return "; ".join(problems) + (f" (+{more} more)" if more > 0 else "")

"""Policy compilation: provider output schema, providers and deterministic validation.

Entry point: `compile_text(text, get_provider())` -> `CompileSuccess | CompileFailure`.
"""

from covered.compiler.anthropic_provider import AnthropicProvider
from covered.compiler.compile import compile_text
from covered.compiler.factory import get_provider
from covered.compiler.mock_provider import UNSUPPORTED_TEXT, MockProvider
from covered.compiler.prompt import PROMPT_VERSION
from covered.compiler.result import (
    CLAUSE_NOT_FOUND,
    CONFLICT_FLAG,
    CompileFailure,
    CompileMeta,
    CompileOutcome,
    CompileSuccess,
    Provider,
    ProviderError,
    ProviderReply,
    ValidatedRule,
    ValidatedUncompilable,
)
from covered.compiler.schema import (
    CompilationResult,
    ProposedRule,
    ProposedUncompilable,
)
from covered.compiler.text import normalize_whitespace, text_sha256

__all__ = [
    "CLAUSE_NOT_FOUND",
    "CONFLICT_FLAG",
    "PROMPT_VERSION",
    "UNSUPPORTED_TEXT",
    "AnthropicProvider",
    "CompilationResult",
    "CompileFailure",
    "CompileMeta",
    "CompileOutcome",
    "CompileSuccess",
    "MockProvider",
    "ProposedRule",
    "ProposedUncompilable",
    "Provider",
    "ProviderError",
    "ProviderReply",
    "ValidatedRule",
    "ValidatedUncompilable",
    "compile_text",
    "get_provider",
    "normalize_whitespace",
    "text_sha256",
]

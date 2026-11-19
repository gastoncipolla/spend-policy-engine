"""Return types of a compilation and the provider contract.

`compile_text` returns `CompileSuccess | CompileFailure`; both carry `CompileMeta`
so the caller can store and log it (SPEC §2 `compile_meta`, §10).
"""

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from covered.domain import Category, RuleParams, UncompilableEffect

CONFLICT_FLAG = "conflict"
CLAUSE_NOT_FOUND = "clause_not_found_in_text"


class CompileMeta(BaseModel):
    """What one provider call cost. Fields are None when unknown."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    cost_usd: Decimal | None = None


class ValidatedRule(BaseModel):
    """A rule that passed deterministic validation, ready to store as `proposed`."""

    model_config = ConfigDict(frozen=True)

    clause: str
    params: RuleParams
    flags: tuple[str, ...] = ()


class ValidatedUncompilable(BaseModel):
    """An uncompilable clause, ready to store as `proposed`."""

    model_config = ConfigDict(frozen=True)

    clause: str
    reason: str
    categories: tuple[Category | Literal["*"], ...]
    effect: UncompilableEffect


class CompileSuccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: Literal[True] = True
    rules: tuple[ValidatedRule, ...]
    uncompilable: tuple[ValidatedUncompilable, ...]
    meta: CompileMeta


class CompileFailure(BaseModel):
    """Nothing usable came back; store `error` as `compile_error`."""

    model_config = ConfigDict(frozen=True)

    ok: Literal[False] = False
    error: str
    meta: CompileMeta


CompileOutcome = CompileSuccess | CompileFailure


class ProviderReply(BaseModel):
    """Raw provider output (JSON text, not yet validated) plus its metadata."""

    model_config = ConfigDict(frozen=True)

    payload: str
    meta: CompileMeta


class ProviderError(Exception):
    """The provider could not produce output (API error, refusal, unknown text...)."""

    def __init__(self, message: str, meta: CompileMeta) -> None:
        super().__init__(message)
        self.message = message
        self.meta = meta


class Provider(Protocol):
    """Anything that turns policy text into a `CompilationResult` JSON payload."""

    name: str

    def propose(self, text: str) -> ProviderReply:
        """Return the raw JSON payload, or raise `ProviderError`."""
        ...

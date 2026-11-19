"""What a provider must return: `CompilationResult` (SPEC §5 step 2).

The same Pydantic models generate the JSON schema sent to the LLM (structured
outputs) and validate whatever comes back, so params use the domain types:
amounts > 0 and catalog categories are enforced here. Anything that does not
validate makes the whole compilation fail (nothing partial).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from covered.domain import Category, RuleParams, UncompilableEffect

NonEmptyText = Annotated[str, Field(min_length=1)]


class ProposedRule(BaseModel):
    """One rule the provider extracted, with the literal clause it encodes."""

    model_config = ConfigDict(extra="forbid")

    clause: NonEmptyText
    """Exact quote from the policy text."""
    params: RuleParams


class ProposedUncompilable(BaseModel):
    """A clause the provider could not express as one of the five rule types."""

    model_config = ConfigDict(extra="forbid")

    clause: NonEmptyText
    """Exact quote from the policy text."""
    reason: NonEmptyText
    categories: Annotated[list[Category | Literal["*"]], Field(min_length=1)]
    """Proposed affected categories, or `["*"]` for all of them."""
    effect: UncompilableEffect
    """Proposed effect; finance confirms or changes it."""


class CompilationResult(BaseModel):
    """Structured output of a compilation provider."""

    model_config = ConfigDict(extra="forbid")

    rules: list[ProposedRule]
    uncompilable: list[ProposedUncompilable]

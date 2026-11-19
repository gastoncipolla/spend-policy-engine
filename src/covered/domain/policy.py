"""What the engine needs from an active policy version (SPEC §4.1).

`CompiledPolicy` = approved rules + confirmed uncompilable clauses. Building it
(filtering by status, loading from storage) is the caller's job.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from covered.domain.categories import Category
from covered.domain.rules import PolicyRule

ALL_CATEGORIES = "*"
"""Marker meaning "every category" in an uncompilable clause's `categories`."""


class UncompilableEffect(StrEnum):
    REQUIRES_REVIEW = "requires_review"
    """Matching expenses get a needs_approval reason citing the clause."""
    INFORMATIONAL = "informational"
    """Matching expenses get a warning citing the clause."""


class ConfirmedUncompilable(BaseModel):
    """A policy clause that cannot be expressed as a rule, classified by finance."""

    model_config = ConfigDict(frozen=True)

    id: int
    clause: Annotated[str, Field(min_length=1)]
    reason: str
    categories: Annotated[list[Category | Literal["*"]], Field(min_length=1)]
    """Catalog categories, or exactly `["*"]` for every category."""
    effect: UncompilableEffect

    @field_validator("categories")
    @classmethod
    def _star_is_alone(cls, value: list[Category | str]) -> list[Category | str]:
        if ALL_CATEGORIES in value and len(value) != 1:
            raise ValueError('"*" cannot be combined with other categories')
        if len(set(value)) != len(value):
            raise ValueError("duplicate categories are not allowed")
        return value

    def applies_to(self, category: Category) -> bool:
        return ALL_CATEGORIES in self.categories or category in self.categories


class CompiledPolicy(BaseModel):
    """The executable form of one active policy version."""

    model_config = ConfigDict(frozen=True)

    policy_id: int
    version: Annotated[int, Field(ge=1)]
    rules: list[PolicyRule] = []
    """Approved rules only, in display order (reasons keep this order)."""
    uncompilable: list[ConfirmedUncompilable] = []
    """Confirmed uncompilable clauses only."""

    @model_validator(mode="after")
    def _unique_ids(self) -> "CompiledPolicy":
        rule_ids = [rule.id for rule in self.rules]
        clause_ids = [item.id for item in self.uncompilable]
        if len(set(rule_ids)) != len(rule_ids) or len(set(clause_ids)) != len(
            clause_ids
        ):
            raise ValueError("rule and uncompilable ids must be unique")
        return self

    def covered_categories(self) -> frozenset[Category]:
        """Categories named explicitly by at least one rule (`other` never counts)."""
        named = frozenset().union(
            *(rule.params.explicit_categories() for rule in self.rules)
        )
        return named - {Category.OTHER}

    def uncovered_categories(self) -> list[Category]:
        """Catalog categories that would get "No rule covers this category", in catalog order."""
        covered = self.covered_categories()
        return [category for category in Category if category not in covered]

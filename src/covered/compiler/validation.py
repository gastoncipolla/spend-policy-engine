"""Deterministic checks on a schema-valid `CompilationResult` (SPEC §5 step 2).

Never trust the provider:
- a rule whose clause is not a literal (whitespace-normalized) substring of the
  policy text is dropped and becomes an uncompilable clause with reason
  `clause_not_found_in_text`;
- two rules of the same type that overlap on a category with different params
  are both flagged `conflict` (activation is blocked while one is approved).
"""

from itertools import combinations

from covered.compiler.result import (
    CLAUSE_NOT_FOUND,
    CONFLICT_FLAG,
    ValidatedRule,
    ValidatedUncompilable,
)
from covered.compiler.schema import CompilationResult, ProposedRule
from covered.compiler.text import clause_in_text
from covered.domain import ALL_CATEGORIES, UncompilableEffect


def validate_result(
    result: CompilationResult, text: str
) -> tuple[list[ValidatedRule], list[ValidatedUncompilable]]:
    """Return the rules to propose and the uncompilable clauses, in provider order."""
    kept: list[ProposedRule] = []
    uncompilable: list[ValidatedUncompilable] = []

    for rule in result.rules:
        if clause_in_text(rule.clause, text):
            kept.append(rule)
        else:
            uncompilable.append(_dropped(rule))

    for item in result.uncompilable:
        # SPEC-QUESTION: the spec only says what to do with rules whose clause is
        # not in the text. An uncompilable clause that is not in the text is kept
        # (finance must still classify it) but its reason is replaced so the
        # reviewer sees the quote is not literal.
        found = clause_in_text(item.clause, text)
        uncompilable.append(
            ValidatedUncompilable(
                clause=item.clause,
                reason=item.reason if found else CLAUSE_NOT_FOUND,
                categories=tuple(item.categories),
                effect=item.effect,
            )
        )

    conflicting = _conflicting_indexes(kept)
    rules = [
        ValidatedRule(
            clause=rule.clause,
            params=rule.params,
            flags=(CONFLICT_FLAG,) if index in conflicting else (),
        )
        for index, rule in enumerate(kept)
    ]
    return rules, uncompilable


def _dropped(rule: ProposedRule) -> ValidatedUncompilable:
    """A hallucinated rule, kept visible as an uncompilable clause for finance."""
    categories = sorted(rule.params.explicit_categories()) or [ALL_CATEGORIES]
    return ValidatedUncompilable(
        clause=rule.clause,
        reason=CLAUSE_NOT_FOUND,
        categories=tuple(categories),
        # Conservative default: finance reclassifies it before activation anyway.
        effect=UncompilableEffect.REQUIRES_REVIEW,
    )


def _conflicting_indexes(rules: list[ProposedRule]) -> set[int]:
    flagged: set[int] = set()
    for (i, a), (j, b) in combinations(enumerate(rules), 2):
        if _conflict(a, b):
            flagged.update((i, j))
    return flagged


def _conflict(a: ProposedRule, b: ProposedRule) -> bool:
    """Same type, overlapping categories, different params.

    A rule without explicit categories (`categories = None`) applies to every
    category, so it overlaps any rule of the same type.
    """
    if a.params.type != b.params.type or a.params == b.params:
        return False
    cats_a = a.params.explicit_categories()
    cats_b = b.params.explicit_categories()
    return not cats_a or not cats_b or bool(cats_a & cats_b)

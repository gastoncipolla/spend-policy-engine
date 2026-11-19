"""Mock provider and the hand-written fixtures for the sample policies."""

from pathlib import Path

import pytest

from covered.compiler import (
    CLAUSE_NOT_FOUND,
    UNSUPPORTED_TEXT,
    MockProvider,
    compile_text,
)
from covered.domain import RuleType, UncompilableEffect

POLICIES = Path(__file__).resolve().parents[2] / "fixtures" / "policies"
SAMPLES = ("sales", "engineering")


def sample(name: str) -> str:
    return (POLICIES / f"{name}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_fixture_validates_cleanly(name):
    outcome = compile_text(sample(name), MockProvider())
    assert outcome.ok, getattr(outcome, "error", None)
    assert outcome.rules
    assert all(rule.flags == () for rule in outcome.rules)
    assert all(item.reason != CLAUSE_NOT_FOUND for item in outcome.uncompilable)
    assert outcome.meta.provider == "mock"


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_has_all_five_rule_types(name):
    outcome = compile_text(sample(name), MockProvider())
    assert {rule.params.type for rule in outcome.rules} == set(RuleType)


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_has_the_required_uncompilable_clauses(name):
    outcome = compile_text(sample(name), MockProvider())
    by_clause = {item.clause: item for item in outcome.uncompilable}
    expected = {
        "Book economy class unless the flight is longer than 8 hours.": (
            ("airfare",),
            UncompilableEffect.REQUIRES_REVIEW,
        ),
        "Client meals require a reasonable business justification.": (
            ("meals",),
            UncompilableEffect.INFORMATIONAL,
        ),
        "Personal expenses are not reimbursable.": (
            ("*",),
            UncompilableEffect.INFORMATIONAL,
        ),
        "We prefer partner hotels whenever one is available.": (
            ("lodging",),
            UncompilableEffect.INFORMATIONAL,
        ),
    }
    assert {
        clause: (item.categories, item.effect) for clause, item in by_clause.items()
    } == expected


def test_sample_policies_differ():
    def meals_limit(name):
        outcome = compile_text(sample(name), MockProvider())
        return next(
            rule.params.amount_minor
            for rule in outcome.rules
            if rule.params.type == "max_amount" and rule.params.category == "meals"
        )

    assert meals_limit("sales") == 8000
    assert meals_limit("engineering") == 5000


def test_whitespace_changes_still_hit_the_fixture():
    reflowed = "\n\n" + sample("sales").replace("\n", "\n   ") + "  \n"
    assert compile_text(reflowed, MockProvider()).ok


def test_unknown_text_fails_with_a_clear_error():
    outcome = compile_text("Meals up to USD 10.", MockProvider())
    assert not outcome.ok
    assert outcome.error == UNSUPPORTED_TEXT
    assert outcome.meta.provider == "mock"


def test_fixtures_dir_is_configurable(tmp_path):
    outcome = compile_text(sample("sales"), MockProvider(fixtures_dir=tmp_path))
    assert not outcome.ok

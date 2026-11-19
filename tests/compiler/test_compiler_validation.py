"""Deterministic validation of provider output (SPEC §5 step 2, §12)."""

from compiler_builders import (
    ALCOHOL_CLAUSE,
    ECONOMY_CLAUSE,
    MEALS_CLAUSE,
    POLICY,
    StaticProvider,
    economy,
    max_meals,
    no_alcohol,
)

from covered.compiler import CLAUSE_NOT_FOUND, CONFLICT_FLAG, compile_text
from covered.domain import UncompilableEffect


def compile_payload(payload):
    return compile_text(POLICY, StaticProvider(payload))


def test_valid_output_is_kept_in_order():
    outcome = compile_payload(
        {"rules": [max_meals(), no_alcohol()], "uncompilable": [economy()]}
    )
    assert outcome.ok
    assert [rule.params.type for rule in outcome.rules] == [
        "max_amount",
        "prohibited_category",
    ]
    assert all(rule.flags == () for rule in outcome.rules)
    assert outcome.uncompilable[0].reason != CLAUSE_NOT_FOUND
    assert outcome.meta.provider == "static"


def test_clause_matches_ignoring_whitespace_runs():
    # The policy breaks the economy clause across two lines.
    spaced = economy() | {
        "clause": "Book  economy class\tunless the flight is longer than 8 hours."
    }
    outcome = compile_payload({"rules": [], "uncompilable": [spaced]})
    assert outcome.uncompilable[0].reason == economy()["reason"]


def test_hallucinated_clause_is_dropped_and_recorded_as_uncompilable():
    invented = max_meals(clause="Meals are reimbursed up to USD 95.00 per expense.")
    outcome = compile_payload({"rules": [invented, no_alcohol()], "uncompilable": []})
    assert outcome.ok
    assert [rule.clause for rule in outcome.rules] == [ALCOHOL_CLAUSE]
    [dropped] = outcome.uncompilable
    assert dropped.clause == invented["clause"]
    assert dropped.reason == CLAUSE_NOT_FOUND
    assert dropped.categories == ("meals",)
    assert dropped.effect is UncompilableEffect.REQUIRES_REVIEW


def test_dropped_rule_for_all_categories_gets_star():
    rule = {
        "clause": "Everything above USD 10.00 needs approval.",
        "params": {"type": "pre_approval_threshold", "amount_minor": 1000},
    }
    outcome = compile_payload({"rules": [rule], "uncompilable": []})
    assert outcome.rules == ()
    assert outcome.uncompilable[0].categories == ("*",)


def test_blank_clause_never_matches():
    outcome = compile_payload({"rules": [max_meals(clause="   ")], "uncompilable": []})
    assert outcome.rules == ()
    assert outcome.uncompilable[0].reason == CLAUSE_NOT_FOUND


def test_uncompilable_with_invented_clause_is_kept_but_marked():
    invented = economy() | {"clause": "First class is fine for directors."}
    outcome = compile_payload({"rules": [], "uncompilable": [invented]})
    assert outcome.uncompilable[0].reason == CLAUSE_NOT_FOUND
    assert outcome.uncompilable[0].clause != ECONOMY_CLAUSE


def test_unknown_category_fails_the_whole_compilation():
    bad = max_meals()
    bad["params"]["category"] = "gifts"
    outcome = compile_payload({"rules": [no_alcohol(), bad], "uncompilable": []})
    assert not outcome.ok
    assert outcome.error.startswith("schema_invalid")
    assert "category" in outcome.error
    assert not hasattr(outcome, "rules")  # nothing partial to store


def test_unknown_category_in_uncompilable_fails():
    bad = economy() | {"categories": ["yachts"]}
    outcome = compile_payload({"rules": [], "uncompilable": [bad]})
    assert not outcome.ok


def test_non_positive_or_fractional_amounts_fail():
    for amount in (0, -100, 80.5):
        outcome = compile_payload({"rules": [max_meals(amount)], "uncompilable": []})
        assert not outcome.ok, amount


def test_schema_violations_fail():
    for payload in (
        "not json",
        {"rules": []},
        {"rules": [], "uncompilable": [], "notes": "extra"},
        {
            "rules": [{"clause": ALCOHOL_CLAUSE, "params": {"category": "alcohol"}}],
            "uncompilable": [],
        },
    ):
        outcome = compile_payload(payload)
        assert not outcome.ok, payload
        assert outcome.error.startswith("schema_invalid")


def test_same_type_same_category_different_params_is_a_conflict():
    outcome = compile_payload(
        {"rules": [max_meals(8000), no_alcohol(), max_meals(6000)], "uncompilable": []}
    )
    assert [rule.flags for rule in outcome.rules] == [
        (CONFLICT_FLAG,),
        (),
        (CONFLICT_FLAG,),
    ]


def test_identical_duplicates_are_not_a_conflict():
    outcome = compile_payload({"rules": [max_meals(), max_meals()], "uncompilable": []})
    assert all(rule.flags == () for rule in outcome.rules)


def test_different_types_on_the_same_category_are_not_a_conflict():
    period = {
        "clause": MEALS_CLAUSE,
        "params": {
            "type": "period_limit",
            "category": "meals",
            "amount_minor": 8000,
            "period": "month",
        },
    }
    outcome = compile_payload({"rules": [max_meals(), period], "uncompilable": []})
    assert all(rule.flags == () for rule in outcome.rules)


def test_rule_for_all_categories_overlaps_any_category():
    outcome = compile_payload(
        {
            "rules": [
                threshold(8000, None),
                threshold(5000, ["software"]),
                threshold(3000, ["meals"]),
            ],
            "uncompilable": [],
        }
    )
    assert all(rule.flags == (CONFLICT_FLAG,) for rule in outcome.rules)


def test_disjoint_category_lists_do_not_conflict():
    outcome = compile_payload(
        {
            "rules": [threshold(8000, ["meals"]), threshold(5000, ["software"])],
            "uncompilable": [],
        }
    )
    assert all(rule.flags == () for rule in outcome.rules)


def threshold(amount, categories):
    return {
        "clause": ALCOHOL_CLAUSE,
        "params": {
            "type": "pre_approval_threshold",
            "amount_minor": amount,
            "categories": categories,
        },
    }

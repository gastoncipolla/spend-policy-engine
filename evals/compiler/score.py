"""Score one compilation against a case's expectations, clause by clause.

A provider output is matched to an expected clause when one quote contains the
other (whitespace-normalized): models sometimes quote a bit more or less.

Labels, per expected clause:
- correct
- wrong_type: a rule of another type.
- wrong_params: right type, wrong params.
- wrong_flags: right params, but the conflict flag differs.
- conservative: expected a rule, got an uncompilable clause (goes to review).
- should_be_uncompilable: compiled as a rule but must not be (the dangerous one).
- wrong_effect: uncompilable as expected, with another proposed effect.
- missed: not in the output at all.
- compile_failed: the whole compilation failed.

Rules whose clause matches no expectation are reported as `extra_rules`.
"""

from dataclasses import dataclass, field

from covered.compiler import CompileOutcome, ValidatedRule, normalize_whitespace
from evals.compiler.cases import Case, Expectation, canonical

CORRECT = "correct"
UNSAFE_LABELS = frozenset(
    {"wrong_type", "wrong_params", "wrong_flags", "should_be_uncompilable"}
)
"""Mistakes that would silently change decisions if finance did not catch them."""


@dataclass(frozen=True)
class ItemScore:
    kind: str
    clause: str
    label: str
    got: tuple[dict, ...] = ()
    """Canonical params of the rules matched to this clause."""


@dataclass
class CaseScore:
    items: list[ItemScore] = field(default_factory=list)
    extra_rules: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def correct(self) -> int:
        return sum(item.label == CORRECT for item in self.items)


def same_clause(a: str, b: str) -> bool:
    a, b = normalize_whitespace(a), normalize_whitespace(b)
    return bool(a) and bool(b) and (a in b or b in a)


def score(case: Case, outcome: CompileOutcome) -> CaseScore:
    if not outcome.ok:
        items = [
            ItemScore(e.kind, e.clause, "compile_failed") for e in case.expectations
        ]
        return CaseScore(items=items, error=outcome.error)

    result = CaseScore()
    for expectation in case.expectations:
        rules = [r for r in outcome.rules if same_clause(r.clause, expectation.clause)]
        uncompilable = [
            u for u in outcome.uncompilable if same_clause(u.clause, expectation.clause)
        ]
        label = _label(expectation, rules, [u.effect for u in uncompilable])
        got = tuple(canonical(r.params) for r in rules)
        result.items.append(ItemScore(expectation.kind, expectation.clause, label, got))

    result.extra_rules = [
        rule.clause
        for rule in outcome.rules
        if not any(same_clause(rule.clause, e.clause) for e in case.expectations)
    ]
    return result


def _label(expectation: Expectation, rules: list[ValidatedRule], effects) -> str:
    if expectation.kind == "not_rule":
        return "should_be_uncompilable" if rules else CORRECT
    if expectation.kind == "uncompilable":
        if rules:
            return "should_be_uncompilable"
        if not effects:
            return "missed"
        if expectation.effect and expectation.effect not in effects:
            return "wrong_effect"
        return CORRECT

    matching = [r for r in rules if canonical(r.params) in expectation.accepted]
    if any(set(r.flags) == set(expectation.flags) for r in matching):
        return CORRECT
    if matching:
        return "wrong_flags"
    expected_type = expectation.accepted[0]["type"]
    if any(r.params.type == expected_type for r in rules):
        return "wrong_params"
    if rules:
        return "wrong_type"
    return "conservative" if effects else "missed"

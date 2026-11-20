"""Policy use cases: compile lifecycle, finance review, activation, immutability."""

import pytest
from service_builders import FINANCE, POLICY_TEXT, SAMPLE_RULES

from covered.domain import Category, MaxAmountParams, UncompilableEffect
from covered.domain.errors import (
    ActivationBlockedError,
    CompileInProgressError,
    InvalidInputError,
    NotFoundError,
    VersionImmutableError,
)
from covered.services import policies
from covered.services.compilation import (
    CompilationFailure,
    CompilationSuccess,
    ProposedRule,
    ProposedUncompilable,
    compile_version,
)
from covered.store import policies as policy_store
from covered.store.db import open_database, transaction
from covered.store.records import (
    RuleOrigin,
    RuleStatus,
    UncompilableStatus,
    VersionStatus,
)

MEALS_CLAUSE = "Meals are capped at USD 50 per expense."
HOTELS_CLAUSE = "Prefer partner hotels when possible."


def _success(*, conflict: bool = False) -> CompilationSuccess:
    return CompilationSuccess(
        rules=[
            ProposedRule(
                params=MaxAmountParams(category=Category.MEALS, amount_minor=5000),
                clause=MEALS_CLAUSE,
                flags=["conflict"] if conflict else [],
            )
        ],
        uncompilable=[ProposedUncompilable(clause=HOTELS_CLAUSE, reason="vague")],
        meta={"model": "fake", "input_tokens": 10},
    )


@pytest.fixture
def draft(conn):
    policy = policies.create_policy(conn, FINANCE, "Engineering")
    policies.create_version(conn, FINANCE, policy.id, POLICY_TEXT)
    return policy.id


def test_create_version_records_who_loaded_the_text(conn):
    policy = policies.create_policy(conn, FINANCE, "Engineering")
    created = policies.create_version(conn, FINANCE, policy.id, POLICY_TEXT)
    assert created.created_by == "fede"
    detail = policies.get_version_detail(conn, FINANCE, policy.id, 1)
    assert detail.created_by == "fede"


def _approve_all(conn, detail):
    for rule in detail.rules:
        policies.update_rule(conn, FINANCE, rule.id, status=RuleStatus.APPROVED)
    for item in detail.uncompilable:
        policies.classify_uncompilable(
            conn,
            FINANCE,
            item.id,
            categories=["lodging"],
            effect=UncompilableEffect.INFORMATIONAL,
        )


# Compilation


def test_compile_success_stores_everything_as_proposed(conn, draft):
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: _success())

    assert detail.status is VersionStatus.DRAFT
    assert detail.compile_meta == {"model": "fake", "input_tokens": 10}
    assert [(r.status, r.origin) for r in detail.rules] == [
        (RuleStatus.PROPOSED, RuleOrigin.LLM)
    ]
    assert detail.uncompilable[0].status is UncompilableStatus.PROPOSED
    assert detail.uncompilable[0].categories == ["*"]


def test_compiler_receives_the_version_text(conn, draft):
    seen = []
    compile_version(
        conn, FINANCE, draft, 1, lambda text: seen.append(text) or _success()
    )
    assert seen == [POLICY_TEXT]


def test_recompile_replaces_llm_proposals_and_keeps_manual_rules(conn, draft):
    policies.add_manual_rule(conn, FINANCE, draft, 1, *SAMPLE_RULES[3])
    compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    assert sorted(r.origin for r in detail.rules) == [RuleOrigin.LLM, RuleOrigin.MANUAL]
    assert len(detail.uncompilable) == 1


def test_compile_failure_sets_status_and_stores_nothing(conn, draft):
    failure = CompilationFailure(error="refusal", meta={"model": "fake"})
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: failure)

    assert detail.status is VersionStatus.COMPILE_FAILED
    assert detail.compile_error == "refusal"
    assert detail.compile_meta == {"model": "fake"}
    assert detail.rules == [] and detail.uncompilable == []


def test_compiler_exception_becomes_compile_failed_and_releases_lock(conn, draft):
    def broken(text):
        raise RuntimeError("network down")

    detail = compile_version(conn, FINANCE, draft, 1, broken)
    assert detail.status is VersionStatus.COMPILE_FAILED
    assert "network down" in detail.compile_error

    retried = compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    assert retried.status is VersionStatus.DRAFT
    assert retried.compile_error is None


def test_invalid_proposal_fails_without_partial_rows(conn, draft):
    bad = CompilationSuccess(
        rules=_success().rules,
        uncompilable=[
            ProposedUncompilable(clause=HOTELS_CLAUSE, reason="x", categories=["spa"])
        ],
    )
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: bad)
    assert detail.status is VersionStatus.COMPILE_FAILED
    assert detail.rules == [] and detail.uncompilable == []


def test_one_compile_at_a_time_per_version(conn, db_path, draft):
    """While the provider runs, a second compile of the same version is refused."""
    second_conn = open_database(db_path)
    errors = []

    def slow_compiler(text):
        try:
            compile_version(second_conn, FINANCE, draft, 1, lambda text: _success())
        except CompileInProgressError as exc:
            errors.append(exc)
        return _success()

    detail = compile_version(conn, FINANCE, draft, 1, slow_compiler)
    assert len(errors) == 1
    assert detail.status is VersionStatus.DRAFT
    assert len(detail.rules) == 1


def test_finance_edits_are_refused_while_compiling(conn, draft):
    with transaction(conn):
        policy_store.set_version_status(conn, draft, 1, VersionStatus.COMPILING)
    with pytest.raises(CompileInProgressError):
        policies.add_manual_rule(conn, FINANCE, draft, 1, *SAMPLE_RULES[0])
    with pytest.raises(CompileInProgressError):
        policies.activate_version(conn, FINANCE, draft, 1)


# Finance review


def test_manual_rule_is_approved_and_must_quote_the_text(conn, draft):
    rule = policies.add_manual_rule(conn, FINANCE, draft, 1, *SAMPLE_RULES[0])
    assert (rule.status, rule.origin) == (RuleStatus.APPROVED, RuleOrigin.MANUAL)

    with pytest.raises(InvalidInputError):
        policies.add_manual_rule(
            conn, FINANCE, draft, 1, SAMPLE_RULES[0][0], "Not in the policy."
        )


def test_manual_rule_clause_match_ignores_whitespace(conn, draft):
    clause = "Ground transport is limited to\n   USD 200 per month."
    rule = policies.add_manual_rule(conn, FINANCE, draft, 1, SAMPLE_RULES[0][0], clause)
    assert rule.id > 0


def test_update_rule_changes_status_and_params(conn, draft):
    rule = compile_version(conn, FINANCE, draft, 1, lambda text: _success()).rules[0]
    new_params = MaxAmountParams(category=Category.MEALS, amount_minor=4000)
    updated = policies.update_rule(
        conn, FINANCE, rule.id, status=RuleStatus.REJECTED, params=new_params
    )
    assert updated.status is RuleStatus.REJECTED and updated.params == new_params


def test_update_rule_needs_something_and_an_existing_rule(conn, draft):
    with pytest.raises(InvalidInputError):
        policies.update_rule(conn, FINANCE, 1)
    with pytest.raises(NotFoundError):
        policies.update_rule(conn, FINANCE, 999, status=RuleStatus.APPROVED)


def test_classify_uncompilable_confirms_and_validates(conn, draft):
    item = compile_version(
        conn, FINANCE, draft, 1, lambda text: _success()
    ).uncompilable[0]
    with pytest.raises(ValueError):
        policies.classify_uncompilable(
            conn,
            FINANCE,
            item.id,
            categories=["*", "lodging"],
            effect=UncompilableEffect.INFORMATIONAL,
        )
    confirmed = policies.classify_uncompilable(
        conn,
        FINANCE,
        item.id,
        categories=["lodging"],
        effect=UncompilableEffect.INFORMATIONAL,
    )
    assert confirmed.status is UncompilableStatus.CONFIRMED


# Activation


@pytest.mark.parametrize("pending", ["rule", "uncompilable"])
def test_activation_blocked_while_review_is_pending(conn, draft, pending):
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    if pending == "uncompilable":
        policies.update_rule(
            conn, FINANCE, detail.rules[0].id, status=RuleStatus.APPROVED
        )
    else:
        policies.classify_uncompilable(
            conn,
            FINANCE,
            detail.uncompilable[0].id,
            categories=["*"],
            effect=UncompilableEffect.REQUIRES_REVIEW,
        )
    with pytest.raises(ActivationBlockedError):
        policies.activate_version(conn, FINANCE, draft, 1)


def test_activation_blocked_by_approved_conflict(conn, draft):
    detail = compile_version(
        conn, FINANCE, draft, 1, lambda text: _success(conflict=True)
    )
    _approve_all(conn, detail)
    with pytest.raises(ActivationBlockedError, match="conflict"):
        policies.activate_version(conn, FINANCE, draft, 1)

    policies.update_rule(conn, FINANCE, detail.rules[0].id, status=RuleStatus.REJECTED)
    assert (
        policies.activate_version(conn, FINANCE, draft, 1).status
        is VersionStatus.ACTIVE
    )


def test_activation_blocked_after_failed_compile(conn, draft):
    compile_version(conn, FINANCE, draft, 1, lambda text: CompilationFailure(error="x"))
    with pytest.raises(ActivationBlockedError):
        policies.activate_version(conn, FINANCE, draft, 1)


def test_activation_retires_previous_and_reports_uncovered(conn, draft):
    _approve_all(
        conn, compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    )
    first = policies.activate_version(conn, FINANCE, draft, 1)
    assert first.activated_by == "fede" and first.activated_at is not None
    assert Category.MEALS not in first.uncovered_categories
    assert Category.OTHER in first.uncovered_categories

    policies.create_version(conn, FINANCE, draft, POLICY_TEXT)
    policies.add_manual_rule(conn, FINANCE, draft, 2, *SAMPLE_RULES[0])
    policies.activate_version(conn, FINANCE, draft, 2)

    assert policy_store.get_version(conn, draft, 1).status is VersionStatus.RETIRED
    summary = policies.list_policies(conn, FINANCE)[0]
    assert summary.active_version == 2


@pytest.mark.parametrize("status", [VersionStatus.ACTIVE, VersionStatus.RETIRED])
def test_active_and_retired_versions_are_immutable(conn, draft, status):
    detail = compile_version(conn, FINANCE, draft, 1, lambda text: _success())
    _approve_all(conn, detail)
    policies.activate_version(conn, FINANCE, draft, 1)
    if status is VersionStatus.RETIRED:
        policies.create_version(conn, FINANCE, draft, POLICY_TEXT)
        policies.activate_version(conn, FINANCE, draft, 2)

    attempts = [
        lambda: policies.update_rule(
            conn, FINANCE, detail.rules[0].id, status=RuleStatus.REJECTED
        ),
        lambda: policies.add_manual_rule(conn, FINANCE, draft, 1, *SAMPLE_RULES[0]),
        lambda: policies.classify_uncompilable(
            conn,
            FINANCE,
            detail.uncompilable[0].id,
            categories=["*"],
            effect=UncompilableEffect.REQUIRES_REVIEW,
        ),
        lambda: compile_version(conn, FINANCE, draft, 1, lambda text: _success()),
        lambda: policies.activate_version(conn, FINANCE, draft, 1),
    ]
    for attempt in attempts:
        with pytest.raises(VersionImmutableError):
            attempt()


def test_missing_policy_and_version_are_not_found(conn):
    with pytest.raises(NotFoundError):
        policies.create_version(conn, FINANCE, 42, "text")
    with pytest.raises(NotFoundError):
        policies.get_version_detail(conn, FINANCE, 42, 1)
    with pytest.raises(InvalidInputError):
        policies.create_policy(conn, FINANCE, "  ")

"""Use case: compile a policy version with an injected compiler (SPEC §5 step 2).

The service owns the lifecycle, not the LLM: it takes the per-version lock
(status `compiling`), calls the compiler outside any transaction, then stores
everything as `proposed` in one transaction, or nothing at all on failure.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from covered.domain import ALL_CATEGORIES, Category, RuleParams, UncompilableEffect
from covered.domain.errors import CoveredError, InvalidInputError
from covered.services.events import log_event
from covered.services.policies import (
    VersionDetail,
    get_version_detail,
    require_editable,
)
from covered.store import policies as policy_store
from covered.store import rules as rule_store
from covered.store.db import transaction
from covered.store.records import (
    RuleOrigin,
    RuleStatus,
    UncompilableStatus,
    VersionStatus,
)


@dataclass(frozen=True)
class ProposedRule:
    """A rule the compiler proposes, already validated against the policy text."""

    params: RuleParams
    clause: str
    flags: Sequence[str] = ()


@dataclass(frozen=True)
class ProposedUncompilable:
    """A clause the compiler could not turn into a rule.

    Defaults are the conservative choice until finance classifies it:
    every category, requires review.
    """

    clause: str
    reason: str
    categories: Sequence[str] = (ALL_CATEGORIES,)
    effect: UncompilableEffect = UncompilableEffect.REQUIRES_REVIEW


@dataclass(frozen=True)
class CompilationSuccess:
    rules: Sequence[ProposedRule] = ()
    uncompilable: Sequence[ProposedUncompilable] = ()
    meta: dict[str, Any] | None = None
    """compile_meta: model, prompt_version, tokens, latency_ms, cost_usd."""


@dataclass(frozen=True)
class CompilationFailure:
    error: str
    meta: dict[str, Any] | None = field(default=None)


CompilationOutcome = CompilationSuccess | CompilationFailure


class Compiler(Protocol):
    def __call__(self, text: str) -> CompilationOutcome: ...


def unconfigured_compiler(text: str) -> CompilationOutcome:
    """Default until a real provider is wired in."""
    return CompilationFailure(error="compiler not configured")


def compile_version(
    conn: sqlite3.Connection, policy_id: int, version: int, compiler: Compiler
) -> VersionDetail:
    """Compile one version. A compile failure is not raised: it is stored on the
    version (`compile_failed` + `compile_error`) and returned in the detail."""
    text = _acquire_lock(conn, policy_id, version)
    try:
        outcome = compiler(text)
    except Exception as exc:  # noqa: BLE001 - any provider error must release the lock
        outcome = CompilationFailure(error=f"compiler error: {exc}")

    if isinstance(outcome, CompilationSuccess):
        try:
            _store_proposals(conn, policy_id, version, outcome)
        except (CoveredError, ValueError, sqlite3.Error) as exc:
            outcome = CompilationFailure(
                error=f"invalid compilation: {exc}", meta=outcome.meta
            )

    if isinstance(outcome, CompilationFailure):
        with transaction(conn, immediate=True):
            policy_store.set_version_status(
                conn,
                policy_id,
                version,
                VersionStatus.COMPILE_FAILED,
                compile_error=outcome.error,
                compile_meta=outcome.meta,
            )

    log_event(
        "policy_compiled",
        policy_id=policy_id,
        version=version,
        outcome="failed" if isinstance(outcome, CompilationFailure) else "ok",
        error=getattr(outcome, "error", None),
        meta=outcome.meta,
    )
    return get_version_detail(conn, policy_id, version)


def _acquire_lock(conn: sqlite3.Connection, policy_id: int, version: int) -> str:
    """Set `compiling` (409 if it already is). Returns the version text."""
    with transaction(conn, immediate=True):
        stored = require_editable(conn, policy_id, version)  # 409 if compiling
        policy_store.set_version_status(
            conn, policy_id, version, VersionStatus.COMPILING
        )
        return stored.text


def _store_proposals(
    conn: sqlite3.Connection,
    policy_id: int,
    version: int,
    outcome: CompilationSuccess,
) -> None:
    """Replace the previous LLM proposals with these, all in one transaction.

    Manual rules are kept; previous LLM rules and uncompilable clauses are replaced.
    """
    for item in outcome.uncompilable:
        _validate_categories(item.categories)
    with transaction(conn, immediate=True):
        rule_store.delete_rules(conn, policy_id, version, RuleOrigin.LLM)
        rule_store.delete_uncompilable(conn, policy_id, version)
        for rule in outcome.rules:
            rule_store.insert_rule(
                conn,
                policy_id=policy_id,
                version=version,
                params=rule.params,
                clause=rule.clause,
                status=RuleStatus.PROPOSED,
                origin=RuleOrigin.LLM,
                flags=rule.flags,
            )
        for item in outcome.uncompilable:
            rule_store.insert_uncompilable(
                conn,
                policy_id=policy_id,
                version=version,
                clause=item.clause,
                reason=item.reason,
                categories=item.categories,
                effect=item.effect,
                status=UncompilableStatus.PROPOSED,
            )
        policy_store.set_version_status(
            conn, policy_id, version, VersionStatus.DRAFT, compile_meta=outcome.meta
        )


def _validate_categories(categories: Sequence[str]) -> None:
    known = {category.value for category in Category} | {ALL_CATEGORIES}
    unknown = [c for c in categories if c not in known]
    if not categories or unknown:
        raise InvalidInputError(f"invalid uncompilable categories: {list(categories)}")

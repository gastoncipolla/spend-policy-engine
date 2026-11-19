"""Use case: compile a policy version with an injected compiler (SPEC §5 step 2).

The service owns the lifecycle, not the LLM: it takes the per-version lock
(status `compiling`), calls the compiler outside any transaction, then stores
everything as `proposed` in one transaction, or nothing at all on failure.

A lock older than `STALE_LOCK_AFTER` is stale (its process died) and is taken
over (SPEC §12b). The lock is identified by `compiling_since`, so a compile
whose lock was taken over stores nothing when it finally returns.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from covered.domain import ALL_CATEGORIES, Category, RuleParams, UncompilableEffect
from covered.domain.errors import CoveredError, InvalidInputError
from covered.services import authz
from covered.services.authz import Actor
from covered.services.events import log_event
from covered.services.policies import (
    VersionDetail,
    get_version_detail,
    require_editable,
    require_version,
)
from covered.store import policies as policy_store
from covered.store import rules as rule_store
from covered.store.db import transaction
from covered.store.records import (
    PolicyVersion,
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

STALE_LOCK_AFTER = timedelta(minutes=5)
"""Provider worst case is timeout x (retries + 1) = 60 s x 4 = 4 min; plus a margin."""


class _LockLost(Exception):
    """Our `compiling` lock was taken over while the compiler was running."""


class Compiler(Protocol):
    def __call__(self, text: str) -> CompilationOutcome: ...


def unconfigured_compiler(text: str) -> CompilationOutcome:
    """Default until a real provider is wired in."""
    return CompilationFailure(error="compiler not configured")


def compile_version(
    conn: sqlite3.Connection,
    actor: Actor,
    policy_id: int,
    version: int,
    compiler: Compiler,
) -> VersionDetail:
    """Compile one version (finance only). A compile failure is not raised: it is
    stored on the version (`compile_failed` + `compile_error`) and returned."""
    authz.require_finance(actor, "compile policies")
    text, lock = _acquire_lock(conn, policy_id, version)
    try:
        outcome = compiler(text)
    except Exception as exc:  # noqa: BLE001 - any provider error must release the lock
        outcome = CompilationFailure(error=f"compiler error: {exc}")

    try:
        outcome = _store_outcome(conn, policy_id, version, lock, outcome)
        result = "failed" if isinstance(outcome, CompilationFailure) else "ok"
    except _LockLost:
        result = "lock_lost"  # a newer compile owns the version; ours is discarded

    log_event(
        "policy_compiled",
        policy_id=policy_id,
        version=version,
        outcome=result,
        error=getattr(outcome, "error", None),
        **(outcome.meta or {}),  # provider, model, prompt_version, tokens, cost
    )
    return get_version_detail(conn, actor, policy_id, version)


def _acquire_lock(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> tuple[str, datetime | None]:
    """Set `compiling` (409 if it already is, unless the lock is stale).

    Returns the version text and the lock (`compiling_since`) we now hold.
    """
    with transaction(conn, immediate=True):
        stored = require_version(conn, policy_id, version)
        if _is_stale(stored):
            log_event(
                "compile_lock_taken_over",
                policy_id=policy_id,
                version=version,
                compiling_since=stored.compiling_since,
            )
        else:
            require_editable(conn, policy_id, version)  # 409 if compiling
        policy_store.set_version_status(
            conn, policy_id, version, VersionStatus.COMPILING
        )
        locked = policy_store.get_version(conn, policy_id, version)
        return stored.text, locked.compiling_since


def _is_stale(stored: PolicyVersion) -> bool:
    if stored.status is not VersionStatus.COMPILING:
        return False
    # SPEC-QUESTION: a `compiling` row without `compiling_since` predates
    # migration 003; with no start time it could never be compiled again, so it
    # is treated as stale.
    if stored.compiling_since is None:
        return True
    return datetime.now(UTC) - stored.compiling_since > STALE_LOCK_AFTER


def _require_lock(
    conn: sqlite3.Connection, policy_id: int, version: int, lock: datetime | None
) -> None:
    """Inside a write transaction: raise `_LockLost` unless we still hold the lock."""
    current = policy_store.get_version(conn, policy_id, version)
    if current.status is not VersionStatus.COMPILING or current.compiling_since != lock:
        log_event("compile_lock_lost", policy_id=policy_id, version=version)
        raise _LockLost


def _store_outcome(
    conn: sqlite3.Connection,
    policy_id: int,
    version: int,
    lock: datetime | None,
    outcome: CompilationOutcome,
) -> CompilationOutcome:
    """Store proposals, or the failure; returns what was stored."""
    if isinstance(outcome, CompilationSuccess):
        try:
            _store_proposals(conn, policy_id, version, lock, outcome)
            return outcome
        except (CoveredError, ValueError, sqlite3.Error) as exc:
            outcome = CompilationFailure(
                error=f"invalid compilation: {exc}", meta=outcome.meta
            )
    with transaction(conn, immediate=True):
        _require_lock(conn, policy_id, version, lock)
        policy_store.set_version_status(
            conn,
            policy_id,
            version,
            VersionStatus.COMPILE_FAILED,
            compile_error=outcome.error,
            compile_meta=outcome.meta,
        )
    return outcome


def _store_proposals(
    conn: sqlite3.Connection,
    policy_id: int,
    version: int,
    lock: datetime | None,
    outcome: CompilationSuccess,
) -> None:
    """Replace the previous LLM proposals with these, all in one transaction.

    Manual rules are kept; previous LLM rules and uncompilable clauses are replaced.
    """
    for item in outcome.uncompilable:
        _validate_categories(item.categories)
    with transaction(conn, immediate=True):
        _require_lock(conn, policy_id, version, lock)
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

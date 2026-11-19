"""Use cases: policies, versions, finance review and activation (SPEC §5).

Active and retired versions are immutable: their rules and uncompilable
clauses never change, so stored decisions stay reproducible.
"""

import sqlite3

from pydantic import BaseModel

from covered.domain import (
    Category,
    CompiledPolicy,
    ConfirmedUncompilable,
    PolicyRule,
    RuleParams,
    UncompilableEffect,
)
from covered.domain.errors import (
    ActivationBlockedError,
    CompileInProgressError,
    InvalidInputError,
    NoActivePolicyError,
    NotFoundError,
    VersionImmutableError,
)
from covered.services.events import log_event
from covered.store import policies as policy_store
from covered.store import rules as rule_store
from covered.store.db import transaction
from covered.store.records import (
    CONFLICT_FLAG,
    Employee,
    Policy,
    PolicyVersion,
    RuleOrigin,
    RuleStatus,
    StoredRule,
    StoredUncompilable,
    UncompilableStatus,
    VersionStatus,
)

IMMUTABLE_STATUSES = frozenset({VersionStatus.ACTIVE, VersionStatus.RETIRED})


class VersionRef(BaseModel):
    version: int
    status: VersionStatus


class PolicySummary(Policy):
    active_version: int | None
    versions: list[VersionRef]


class VersionDetail(PolicyVersion):
    """A version with its rules, uncompilable clauses and uncovered categories.

    `uncovered_categories` is computed from the currently approved rules.
    """

    rules: list[StoredRule]
    uncompilable: list[StoredUncompilable]
    uncovered_categories: list[Category]


# Policies and versions


def create_policy(conn: sqlite3.Connection, name: str) -> Policy:
    name = name.strip()
    if not name:
        raise InvalidInputError("policy name must not be empty")
    with transaction(conn):
        return policy_store.insert_policy(conn, name)


def list_policies(conn: sqlite3.Connection) -> list[PolicySummary]:
    summaries = []
    for policy in policy_store.list_policies(conn):
        versions = policy_store.list_versions(conn, policy.id)
        active = [v.version for v in versions if v.status is VersionStatus.ACTIVE]
        summaries.append(
            PolicySummary(
                id=policy.id,
                name=policy.name,
                active_version=active[0] if active else None,
                versions=[
                    VersionRef(version=v.version, status=v.status) for v in versions
                ],
            )
        )
    return summaries


def create_version(
    conn: sqlite3.Connection, policy_id: int, text: str
) -> PolicyVersion:
    if not text.strip():
        raise InvalidInputError("policy text must not be empty")
    with transaction(conn, immediate=True):
        if policy_store.get_policy(conn, policy_id) is None:
            raise NotFoundError(f"policy {policy_id} not found")
        return policy_store.insert_version(conn, policy_id, text)


def get_version_detail(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> VersionDetail:
    with transaction(conn):
        return _detail(conn, require_version(conn, policy_id, version))


# Finance review


def add_manual_rule(
    conn: sqlite3.Connection,
    policy_id: int,
    version: int,
    params: RuleParams,
    clause: str,
) -> StoredRule:
    """A rule written by finance: origin=manual, status=approved."""
    with transaction(conn, immediate=True):
        stored_version = require_editable(conn, policy_id, version)
        # SPEC-QUESTION: the spec does not say where a manual rule's clause comes
        # from. Every outcome must cite the literal policy clause (§1.4), so we
        # require it to be a substring of the version text, like compiled rules.
        if not clause_in_text(clause, stored_version.text):
            raise InvalidInputError(
                "clause must be a literal quote from the policy text"
            )
        return rule_store.insert_rule(
            conn,
            policy_id=policy_id,
            version=version,
            params=params,
            clause=clause.strip(),
            status=RuleStatus.APPROVED,
            origin=RuleOrigin.MANUAL,
        )


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    *,
    status: RuleStatus | None = None,
    params: RuleParams | None = None,
) -> StoredRule:
    """Approve/reject/edit a rule of a non-active version. Flags are kept as they are."""
    if status is None and params is None:
        raise InvalidInputError("nothing to update: pass status and/or params")
    with transaction(conn, immediate=True):
        rule = rule_store.get_rule(conn, rule_id)
        if rule is None:
            raise NotFoundError(f"rule {rule_id} not found")
        require_editable(conn, rule.policy_id, rule.version)
        return rule_store.update_rule(conn, rule_id, status=status, params=params)


def classify_uncompilable(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    categories: list[str],
    effect: UncompilableEffect,
) -> StoredUncompilable:
    """Finance sets categories and effect; the clause becomes confirmed."""
    with transaction(conn, immediate=True):
        item = rule_store.get_uncompilable(conn, item_id)
        if item is None:
            raise NotFoundError(f"uncompilable clause {item_id} not found")
        require_editable(conn, item.policy_id, item.version)
        # Reuse the domain validation (catalog categories, "*" alone, no duplicates).
        ConfirmedUncompilable(
            id=item.id,
            clause=item.clause,
            reason=item.reason,
            categories=categories,
            effect=effect,
        )
        return rule_store.classify_uncompilable(
            conn, item_id, categories=categories, effect=effect
        )


# Activation


def activate_version(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> VersionDetail:
    """SPEC §5 step 4: block on pending review or approved conflicts, then swap active."""
    with transaction(conn, immediate=True):
        stored_version = require_editable(conn, policy_id, version)
        if stored_version.status is VersionStatus.COMPILE_FAILED:
            raise ActivationBlockedError("the last compile failed: compile again first")
        problems = _activation_problems(conn, policy_id, version)
        if problems:
            raise ActivationBlockedError("cannot activate: " + "; ".join(problems))
        policy_store.retire_active_version(conn, policy_id)
        policy_store.set_version_status(
            conn,
            policy_id,
            version,
            VersionStatus.ACTIVE,
            compile_meta=stored_version.compile_meta,
        )
        detail = _detail(conn, policy_store.get_version(conn, policy_id, version))
    log_event(
        "policy_activated",
        policy_id=policy_id,
        version=version,
        uncovered_categories=detail.uncovered_categories,
    )
    return detail


def _activation_problems(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> list[str]:
    rules = rule_store.list_rules(conn, policy_id, version)
    items = rule_store.list_uncompilable(conn, policy_id, version)
    proposed = [r.id for r in rules if r.status is RuleStatus.PROPOSED]
    unconfirmed = [i.id for i in items if i.status is not UncompilableStatus.CONFIRMED]
    conflicts = [
        r.id
        for r in rules
        if r.status is RuleStatus.APPROVED and CONFLICT_FLAG in r.flags
    ]
    problems = []
    if proposed:
        problems.append(f"rules still proposed: {proposed}")
    if unconfirmed:
        problems.append(f"uncompilable clauses not confirmed: {unconfirmed}")
    if conflicts:
        problems.append(f"approved rules flagged as conflict: {conflicts}")
    return problems


# Compiled policies for the engine


def compiled_policy(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> CompiledPolicy:
    """Approved rules + confirmed uncompilable clauses of one version."""
    rules = rule_store.list_rules(conn, policy_id, version)
    items = rule_store.list_uncompilable(conn, policy_id, version)
    return CompiledPolicy(
        policy_id=policy_id,
        version=version,
        rules=[
            PolicyRule(id=r.id, clause=r.clause, params=r.params)
            for r in rules
            if r.status is RuleStatus.APPROVED
        ],
        uncompilable=[
            ConfirmedUncompilable(
                id=i.id,
                clause=i.clause,
                reason=i.reason,
                categories=i.categories,
                effect=i.effect,
            )
            for i in items
            if i.status is UncompilableStatus.CONFIRMED
        ],
    )


def active_policy_for(conn: sqlite3.Connection, employee: Employee) -> CompiledPolicy:
    """The employee's active compiled policy. No active version is an error, never an approval."""
    active = (
        policy_store.get_active_version(conn, employee.policy_id)
        if employee.policy_id is not None
        else None
    )
    if active is None:
        raise NoActivePolicyError(f"employee {employee.id!r} has no active policy")
    return compiled_policy(conn, active.policy_id, active.version)


# Shared helpers


def require_version(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> PolicyVersion:
    stored = policy_store.get_version(conn, policy_id, version)
    if stored is None:
        raise NotFoundError(f"policy {policy_id} version {version} not found")
    return stored


def require_editable(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> PolicyVersion:
    """The version exists, is not active/retired and is not being compiled."""
    stored = require_version(conn, policy_id, version)
    if stored.status in IMMUTABLE_STATUSES:
        raise VersionImmutableError(
            f"policy {policy_id} version {version} is {stored.status} and cannot change"
        )
    if stored.status is VersionStatus.COMPILING:
        raise CompileInProgressError(
            f"policy {policy_id} version {version} is compiling"
        )
    return stored


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def clause_in_text(clause: str, text: str) -> bool:
    normalized = normalize_whitespace(clause)
    return bool(normalized) and normalized in normalize_whitespace(text)


def _detail(conn: sqlite3.Connection, version: PolicyVersion) -> VersionDetail:
    policy_id, number = version.policy_id, version.version
    return VersionDetail(
        **version.model_dump(),
        rules=rule_store.list_rules(conn, policy_id, number),
        uncompilable=rule_store.list_uncompilable(conn, policy_id, number),
        uncovered_categories=compiled_policy(
            conn, policy_id, number
        ).uncovered_categories(),
    )

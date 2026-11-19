"""Stale compile lock takeover (SPEC §12b)."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from service_builders import FINANCE, POLICY_TEXT

from covered.domain import Category, MaxAmountParams
from covered.domain.errors import CompileInProgressError
from covered.services.compilation import (
    STALE_LOCK_AFTER,
    CompilationSuccess,
    ProposedRule,
    compile_version,
)
from covered.store import policies as policy_store
from covered.store.db import open_database, to_utc_iso, transaction
from covered.store.records import VersionStatus

MEALS_CLAUSE = "Meals are capped at USD 50 per expense."


def _rule(amount_minor: int) -> CompilationSuccess:
    params = MaxAmountParams(category=Category.MEALS, amount_minor=amount_minor)
    return CompilationSuccess(rules=[ProposedRule(params=params, clause=MEALS_CLAUSE)])


@pytest.fixture
def draft(conn):
    with transaction(conn):
        policy = policy_store.insert_policy(conn, "Sales")
        policy_store.insert_version(conn, policy.id, POLICY_TEXT)
    return policy.id


def _lock(conn, policy_id: int, since: datetime | None) -> None:
    """Leave the version in `compiling`, as a crashed compile would."""
    with transaction(conn):
        policy_store.set_version_status(conn, policy_id, 1, VersionStatus.COMPILING)
        conn.execute(
            "UPDATE policy_versions SET compiling_since = ? WHERE policy_id = ?",
            (to_utc_iso(since) if since else None, policy_id),
        )


def _events(caplog) -> list[dict]:
    return [json.loads(record.getMessage()) for record in caplog.records]


def test_compiling_since_is_set_while_compiling_and_cleared_after(conn, draft):
    seen = []

    def compiler(text):
        seen.append(policy_store.get_version(conn, draft, 1).compiling_since)
        return _rule(5000)

    detail = compile_version(conn, FINANCE, draft, 1, compiler)
    assert seen[0] is not None
    assert datetime.now(UTC) - seen[0] < timedelta(minutes=1)
    assert detail.status is VersionStatus.DRAFT
    assert detail.compiling_since is None


def test_a_recent_lock_is_still_refused(conn, draft):
    _lock(conn, draft, datetime.now(UTC) - STALE_LOCK_AFTER + timedelta(seconds=30))
    with pytest.raises(CompileInProgressError):
        compile_version(conn, FINANCE, draft, 1, lambda text: _rule(5000))


@pytest.mark.parametrize(
    "since",
    [datetime.now(UTC) - STALE_LOCK_AFTER - timedelta(seconds=1), None],
    ids=["older-than-5-minutes", "no-compiling-since"],
)
def test_a_stale_lock_is_taken_over_and_logged(conn, draft, caplog, since):
    _lock(conn, draft, since)
    with caplog.at_level(logging.INFO, logger="covered"):
        detail = compile_version(conn, FINANCE, draft, 1, lambda text: _rule(5000))

    assert detail.status is VersionStatus.DRAFT
    assert len(detail.rules) == 1
    takeover = [e for e in _events(caplog) if e["event"] == "compile_lock_taken_over"]
    assert takeover == [
        {
            "event": "compile_lock_taken_over",
            "policy_id": draft,
            "version": 1,
            "compiling_since": None if since is None else str(since),
        }
    ]


def test_a_compile_whose_lock_was_taken_over_stores_nothing(
    conn, db_path, draft, caplog
):
    """The slow compile returns after another one took its stale lock over."""
    other = open_database(db_path)

    def slow_compiler(text):
        _lock(other, draft, datetime.now(UTC) - STALE_LOCK_AFTER * 2)
        compile_version(other, FINANCE, draft, 1, lambda text: _rule(7000))
        return _rule(5000)

    with caplog.at_level(logging.INFO, logger="covered"):
        detail = compile_version(conn, FINANCE, draft, 1, slow_compiler)

    assert [rule.params.amount_minor for rule in detail.rules] == [7000]
    assert detail.status is VersionStatus.DRAFT
    outcomes = [
        e["outcome"] for e in _events(caplog) if e["event"] == "policy_compiled"
    ]
    assert outcomes == ["ok", "lock_lost"]
    other.close()

"""Store: migrations, DB path resolution and repository round trips."""

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from covered.domain import (
    Category,
    Decision,
    ExpenseInput,
    MaxAmountParams,
    Outcome,
    Reason,
    ReasonSource,
    UncompilableEffect,
)
from covered.store import employees, expenses, idempotency, policies, rules
from covered.store.db import migrate, open_database, resolve_db_path, transaction
from covered.store.records import (
    ExpenseStatus,
    RuleOrigin,
    RuleStatus,
    UncompilableStatus,
    VersionStatus,
)

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@pytest.fixture
def conn() -> sqlite3.Connection:
    return open_database(":memory:")


def _expense(amount: int, day: int, **overrides) -> ExpenseInput:
    return ExpenseInput(
        employee_id="ana",
        amount_minor=amount,
        category=overrides.pop("category", Category.MEALS),
        occurred_at=datetime(2026, 11, day, 12, 0, tzinfo=TZ),
        **overrides,
    )


def test_migrations_apply_once(conn):
    assert migrate(conn) == []
    names = [row["name"] for row in conn.execute("SELECT name FROM schema_migrations")]
    assert names == ["001_initial.sql"]


def test_db_path_from_env_creates_folder(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "covered.db"
    monkeypatch.setenv("COVERED_DB", str(target))
    assert resolve_db_path() == str(target)
    assert target.parent.is_dir()
    open_database().close()
    assert target.exists()


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError), transaction(conn):
        policies.insert_policy(conn, "Sales")
        raise RuntimeError("boom")
    assert policies.list_policies(conn) == []


def test_versions_are_numbered_and_one_active_per_policy(conn):
    policy = policies.insert_policy(conn, "Sales")
    first = policies.insert_version(conn, policy.id, "v1 text")
    second = policies.insert_version(conn, policy.id, "v2 text")
    assert (first.version, second.version) == (1, 2)
    assert first.status is VersionStatus.DRAFT

    policies.set_version_status(conn, policy.id, 1, VersionStatus.ACTIVE)
    with pytest.raises(sqlite3.IntegrityError):
        policies.set_version_status(conn, policy.id, 2, VersionStatus.ACTIVE)

    policies.set_version_status(
        conn,
        policy.id,
        2,
        VersionStatus.COMPILE_FAILED,
        compile_error="x",
        compile_meta={"model": "m"},
    )
    stored = policies.get_version(conn, policy.id, 2)
    assert (stored.compile_error, stored.compile_meta) == ("x", {"model": "m"})
    assert policies.get_active_version(conn, policy.id).version == 1


def test_rule_and_uncompilable_round_trip(conn):
    policy = policies.insert_policy(conn, "Sales")
    policies.insert_version(conn, policy.id, "text")
    params = MaxAmountParams(category=Category.MEALS, amount_minor=5000)
    rule = rules.insert_rule(
        conn,
        policy_id=policy.id,
        version=1,
        params=params,
        clause="clause",
        status=RuleStatus.PROPOSED,
        origin=RuleOrigin.LLM,
        flags=["conflict"],
    )
    assert rule.params == params and rule.flags == ["conflict"]
    updated = rules.update_rule(conn, rule.id, status=RuleStatus.APPROVED)
    assert updated.status is RuleStatus.APPROVED

    item = rules.insert_uncompilable(
        conn,
        policy_id=policy.id,
        version=1,
        clause="prefer partner hotels",
        reason="vague",
        categories=["*"],
        effect=UncompilableEffect.REQUIRES_REVIEW,
        status=UncompilableStatus.PROPOSED,
    )
    confirmed = rules.classify_uncompilable(
        conn, item.id, categories=["lodging"], effect=UncompilableEffect.INFORMATIONAL
    )
    assert confirmed.status is UncompilableStatus.CONFIRMED
    assert confirmed.categories == ["lodging"]


def test_period_totals_split_status_and_ignore_rejected_and_outside_window(conn):
    employees.insert_employee(conn, "ana", "Ana", None)
    expenses.insert_expense(conn, _expense(100, 2), ExpenseStatus.APPROVED)
    expenses.insert_expense(conn, _expense(200, 3), ExpenseStatus.PENDING)
    expenses.insert_expense(conn, _expense(400, 4), ExpenseStatus.REJECTED)
    expenses.insert_expense(
        conn, _expense(800, 4, category=Category.LODGING), ExpenseStatus.APPROVED
    )
    expenses.insert_expense(conn, _expense(1600, 30), ExpenseStatus.APPROVED)

    start = datetime(2026, 11, 1, tzinfo=TZ)
    end = datetime(2026, 11, 30, tzinfo=TZ)
    totals = expenses.period_totals(conn, "ana", Category.MEALS, start, end)
    assert (totals.approved_sum, totals.pending_sum) == (100, 200)


def test_expense_and_decision_round_trip(conn):
    employees.insert_employee(conn, "ana", "Ana", None)
    stored = expenses.insert_expense(conn, _expense(100, 2), ExpenseStatus.PENDING)
    assert stored.occurred_at == datetime(2026, 11, 2, 12, 0, tzinfo=TZ)
    decision = Decision(
        expense_id=stored.id,
        employee_id="ana",
        policy_id=1,
        policy_version=1,
        outcome=Outcome.NEEDS_APPROVAL,
        reasons=[
            Reason(
                source=ReasonSource.UNCOVERED_CATEGORY,
                outcome=Outcome.NEEDS_APPROVAL,
                message="No rule covers this category",
            )
        ],
        warnings=[],
        evaluated_at=datetime(2026, 11, 2, 15, 0, tzinfo=TZ),
    )
    expenses.insert_decision(conn, decision)
    assert expenses.get_decision_for_expense(conn, stored.id) == decision

    expenses.set_expense_status(conn, stored.id, ExpenseStatus.APPROVED)
    listed = expenses.list_expenses(
        conn, employee_id="ana", status=ExpenseStatus.APPROVED
    )
    assert [item.id for item in listed] == [stored.id]


def test_idempotency_record_round_trip(conn):
    assert idempotency.get_record(conn, "k1") is None
    idempotency.insert_record(conn, "k1", "hash", 201, {"a": 1})
    record = idempotency.get_record(conn, "k1")
    assert (record.request_hash, record.status_code, record.response) == (
        "hash",
        201,
        {"a": 1},
    )
    with pytest.raises(sqlite3.IntegrityError):
        idempotency.insert_record(conn, "k1", "other", 201, {})

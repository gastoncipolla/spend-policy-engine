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
    Role,
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
    assert names == [
        "001_initial.sql",
        "002_roles_and_audit.sql",
        "003_compiling_since.sql",
        "004_data_model_integrity.sql",
        "005_roles.sql",
    ]


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
    assert rule.reviewed_by is None and rule.reviewed_at is None
    updated = rules.update_rule(
        conn, rule.id, status=RuleStatus.APPROVED, reviewed_by="fede"
    )
    assert updated.status is RuleStatus.APPROVED
    assert updated.reviewed_by == "fede" and updated.reviewed_at is not None

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
        conn,
        item.id,
        categories=["lodging"],
        effect=UncompilableEffect.INFORMATIONAL,
        classified_by="fede",
    )
    assert confirmed.status is UncompilableStatus.CONFIRMED
    assert confirmed.classified_by == "fede" and confirmed.classified_at
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

    expenses.resolve_expense(conn, stored.id, ExpenseStatus.APPROVED, "bruno")
    listed = expenses.list_expenses(
        conn, employee_ids=["ana"], status=ExpenseStatus.APPROVED
    )
    assert [item.id for item in listed] == [stored.id]
    assert listed[0].resolved_by == "bruno" and listed[0].resolved_at is not None
    assert expenses.list_expenses(conn, employee_ids=[]) == []


def test_employee_roles_manager_and_token(conn):
    employees.insert_employee(
        conn, "bruno", "Bruno", None, roles=[Role.MANAGER, Role.EMPLOYEE], token="t-b"
    )
    employees.insert_employee(conn, "ana", "Ana", None, manager_id="bruno")
    bruno = employees.get_employee_by_token(conn, "t-b")
    assert bruno.roles == {Role.EMPLOYEE, Role.MANAGER}
    assert bruno.model_dump(mode="json")["roles"] == ["employee", "manager"]
    assert "token" not in bruno.model_dump()
    ana = employees.get_employee(conn, "ana")
    assert (ana.roles, ana.manager_id) == ({Role.EMPLOYEE}, "bruno")
    assert employees.get_employee_by_token(conn, "nope") is None
    with pytest.raises(sqlite3.IntegrityError):
        employees.insert_employee(conn, "x", "X", None, manager_id="nobody")


def test_idempotency_record_round_trip(conn):
    assert idempotency.get_record(conn, "ana", "k1") is None
    idempotency.insert_record(conn, "ana", "k1", "hash", 201, {"a": 1})
    record = idempotency.get_record(conn, "ana", "k1")
    assert (record.actor_id, record.request_hash, record.response) == (
        "ana",
        "hash",
        {"a": 1},
    )
    assert record.status_code == 201
    with pytest.raises(sqlite3.IntegrityError):
        idempotency.insert_record(conn, "ana", "k1", "other", 201, {})


def test_idempotency_keys_are_scoped_per_actor(conn):
    idempotency.insert_record(conn, "ana", "k1", "hash-a", 201, {"a": 1})
    idempotency.insert_record(conn, "bruno", "k1", "hash-b", 201, {"b": 2})
    assert idempotency.get_record(conn, "ana", "k1").request_hash == "hash-a"
    assert idempotency.get_record(conn, "bruno", "k1").request_hash == "hash-b"
    assert idempotency.get_record(conn, "carla", "k1") is None


def _decision(expense_id: int | None) -> Decision:
    return Decision(
        expense_id=expense_id,
        employee_id="ana",
        policy_id=1,
        policy_version=1,
        outcome=Outcome.APPROVED,
        reasons=[],
        warnings=[],
        evaluated_at=datetime(2026, 11, 2, 15, 0, tzinfo=TZ),
    )


def test_decision_without_expense_is_never_stored(conn):
    with pytest.raises(ValueError, match="submitted expenses"):
        expenses.insert_decision(conn, _decision(None))
    # The schema enforces it too, below the repository.
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        conn.execute(
            "INSERT INTO decisions (expense_id, employee_id, policy_id, policy_version,"
            " outcome, reasons, warnings, evaluated_at)"
            " VALUES (NULL, 'ana', 1, 1, 'approved', '[]', '[]', 'x')"
        )
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0


def test_version_records_created_by(conn):
    policy = policies.insert_policy(conn, "Sales")
    assert policies.insert_version(conn, policy.id, "v1", "fede").created_by == "fede"
    assert policies.insert_version(conn, policy.id, "v2").created_by is None

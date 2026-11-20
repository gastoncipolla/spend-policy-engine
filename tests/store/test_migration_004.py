"""Migration 004 upgrades a database created before it without losing data."""

import json
import sqlite3
from importlib import resources

import pytest

from covered.store import expenses, idempotency, policies
from covered.store.db import _statements, connect, migrate

BEFORE_004 = ["001_initial.sql", "002_roles_and_audit.sql", "003_compiling_since.sql"]


def _database_before_004(path: str) -> sqlite3.Connection:
    """The schema as it was before 004, applied the way the runner does."""
    conn = connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    folder = resources.files("covered.store") / "migrations"
    for name in BEFORE_004:
        for statement in _statements((folder / name).read_text(encoding="utf-8")):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations VALUES (?, 'then')", (name,))
    return conn


def _seed_old_rows(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO policies (id, name) VALUES (1, 'Sales');
        INSERT INTO policy_versions (policy_id, version, text, status, created_at,
                                     activated_by, activated_at)
            VALUES (1, 1, 'text', 'active', '2026-11-01T00:00:00+00:00', 'fede',
                    '2026-11-01T01:00:00+00:00');
        INSERT INTO employees (id, name, policy_id) VALUES ('ana', 'Ana', 1);
        INSERT INTO expenses (id, employee_id, amount_minor, currency, category,
                              occurred_at, occurred_at_utc, status, created_at)
            VALUES (1, 'ana', 6000, 'USD', 'meals', 't', 't', 'approved', 't'),
                   (2, 'ana', 7000, 'USD', 'meals', 't', 't', 'approved', 't');
        INSERT INTO decisions (id, expense_id, employee_id, policy_id, policy_version,
                               outcome, reasons, warnings, evaluated_at)
            VALUES (5, 1, 'ana', 1, 1, 'approved', '[]', '[]', '2026-11-02T18:00:00+00:00'),
                   (6, 2, 'ana', 1, 1, 'approved', '[]', '[]', '2026-11-02T18:00:00+00:00');
        DELETE FROM decisions WHERE id = 6;
        """
    )
    body = {"expense": {"id": 1, "employee_id": "ana"}, "decision": {}}
    conn.execute(
        "INSERT INTO idempotency_records VALUES ('k1', 'hash', 201, ?, '2026-11-02T18:00:00+00:00')",
        (json.dumps(body),),
    )


def test_migration_004_keeps_existing_rows(tmp_path):
    conn = _database_before_004(str(tmp_path / "old.db"))
    _seed_old_rows(conn)

    assert migrate(conn) == ["004_data_model_integrity.sql", "005_roles.sql"]

    version = policies.get_version(conn, 1, 1)
    assert (version.created_by, version.activated_by) == (None, "fede")
    assert expenses.get_decision_for_expense(conn, 1).expense_id == 1
    record = idempotency.get_record(conn, "ana", "k1")
    assert (record.request_hash, record.response["expense"]["id"]) == ("hash", 1)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    # Constraints of the rebuilt tables hold, and decision ids are never reused.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (expense_id, employee_id, policy_id, policy_version,"
            " outcome, reasons, warnings, evaluated_at)"
            " VALUES (1, 'ana', 1, 1, 'approved', '[]', '[]', 'x')"
        )
    cursor = conn.execute(
        "INSERT INTO decisions (expense_id, employee_id, policy_id, policy_version,"
        " outcome, reasons, warnings, evaluated_at)"
        " VALUES (2, 'ana', 1, 1, 'approved', '[]', '[]', 'x')"
    )
    assert cursor.lastrowid == 7
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (expense_id, employee_id, policy_id, policy_version,"
            " outcome, reasons, warnings, evaluated_at)"
            " VALUES (99, 'ana', 1, 1, 'approved', '[]', '[]', 'x')"
        )

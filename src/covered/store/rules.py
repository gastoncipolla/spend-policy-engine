"""Repository: rules and uncompilable clauses of a policy version."""

import json
import sqlite3
from collections.abc import Sequence

from pydantic import TypeAdapter

from covered.domain import RuleParams, UncompilableEffect
from covered.store.db import utc_now_iso
from covered.store.records import (
    RuleOrigin,
    RuleStatus,
    StoredRule,
    StoredUncompilable,
    UncompilableStatus,
)

_params_adapter: TypeAdapter[RuleParams] = TypeAdapter(RuleParams)


# Rules


def insert_rule(
    conn: sqlite3.Connection,
    *,
    policy_id: int,
    version: int,
    params: RuleParams,
    clause: str,
    status: RuleStatus,
    origin: RuleOrigin,
    flags: Sequence[str] = (),
    reviewed_by: str | None = None,
) -> StoredRule:
    """`reviewed_by` is set when a person writes the rule (manual rules)."""
    cursor = conn.execute(
        "INSERT INTO rules (policy_id, version, type, params, clause, status, origin,"
        " flags, reviewed_by, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            policy_id,
            version,
            params.type,
            params.model_dump_json(),
            clause,
            status,
            origin,
            json.dumps(list(flags)),
            reviewed_by,
            utc_now_iso() if reviewed_by else None,
        ),
    )
    return get_rule(conn, cursor.lastrowid)


def get_rule(conn: sqlite3.Connection, rule_id: int) -> StoredRule | None:
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    return _rule(row) if row else None


def list_rules(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> list[StoredRule]:
    rows = conn.execute(
        "SELECT * FROM rules WHERE policy_id = ? AND version = ? ORDER BY id",
        (policy_id, version),
    )
    return [_rule(row) for row in rows]


def update_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    *,
    status: RuleStatus | None = None,
    params: RuleParams | None = None,
    reviewed_by: str,
) -> StoredRule:
    """Change status and/or params, recording who reviewed it and when."""
    conn.execute(
        "UPDATE rules SET reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (reviewed_by, utc_now_iso(), rule_id),
    )
    if status is not None:
        conn.execute("UPDATE rules SET status = ? WHERE id = ?", (status, rule_id))
    if params is not None:
        conn.execute(
            "UPDATE rules SET type = ?, params = ? WHERE id = ?",
            (params.type, params.model_dump_json(), rule_id),
        )
    return get_rule(conn, rule_id)


def delete_rules(
    conn: sqlite3.Connection, policy_id: int, version: int, origin: RuleOrigin
) -> None:
    conn.execute(
        "DELETE FROM rules WHERE policy_id = ? AND version = ? AND origin = ?",
        (policy_id, version, origin),
    )


def _rule(row: sqlite3.Row) -> StoredRule:
    return StoredRule(
        id=row["id"],
        policy_id=row["policy_id"],
        version=row["version"],
        type=row["type"],
        params=_params_adapter.validate_json(row["params"]),
        clause=row["clause"],
        status=row["status"],
        origin=row["origin"],
        flags=json.loads(row["flags"]),
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
    )


# Uncompilable clauses


def insert_uncompilable(
    conn: sqlite3.Connection,
    *,
    policy_id: int,
    version: int,
    clause: str,
    reason: str,
    categories: Sequence[str],
    effect: UncompilableEffect,
    status: UncompilableStatus,
) -> StoredUncompilable:
    cursor = conn.execute(
        "INSERT INTO uncompilable"
        " (policy_id, version, clause, reason, categories, effect, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            policy_id,
            version,
            clause,
            reason,
            json.dumps(list(categories)),
            effect,
            status,
        ),
    )
    return get_uncompilable(conn, cursor.lastrowid)


def get_uncompilable(
    conn: sqlite3.Connection, item_id: int
) -> StoredUncompilable | None:
    row = conn.execute("SELECT * FROM uncompilable WHERE id = ?", (item_id,)).fetchone()
    return _uncompilable(row) if row else None


def list_uncompilable(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> list[StoredUncompilable]:
    rows = conn.execute(
        "SELECT * FROM uncompilable WHERE policy_id = ? AND version = ? ORDER BY id",
        (policy_id, version),
    )
    return [_uncompilable(row) for row in rows]


def classify_uncompilable(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    categories: Sequence[str],
    effect: UncompilableEffect,
    classified_by: str,
) -> StoredUncompilable:
    """Store finance's classification, mark the clause confirmed, record who/when."""
    conn.execute(
        "UPDATE uncompilable SET categories = ?, effect = ?, status = ?,"
        " classified_by = ?, classified_at = ? WHERE id = ?",
        (
            json.dumps(list(categories)),
            effect,
            UncompilableStatus.CONFIRMED,
            classified_by,
            utc_now_iso(),
            item_id,
        ),
    )
    return get_uncompilable(conn, item_id)


def delete_uncompilable(conn: sqlite3.Connection, policy_id: int, version: int) -> None:
    conn.execute(
        "DELETE FROM uncompilable WHERE policy_id = ? AND version = ?",
        (policy_id, version),
    )


def _uncompilable(row: sqlite3.Row) -> StoredUncompilable:
    data = dict(row)
    data["categories"] = json.loads(data["categories"])
    return StoredUncompilable(**data)

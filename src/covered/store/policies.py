"""Repository: policies and policy versions."""

import json
import sqlite3
from typing import Any

from covered.store.db import utc_now_iso
from covered.store.records import Policy, PolicyVersion, VersionStatus


def insert_policy(conn: sqlite3.Connection, name: str) -> Policy:
    cursor = conn.execute("INSERT INTO policies (name) VALUES (?)", (name,))
    return Policy(id=cursor.lastrowid, name=name)


def get_policy(conn: sqlite3.Connection, policy_id: int) -> Policy | None:
    row = conn.execute("SELECT * FROM policies WHERE id = ?", (policy_id,)).fetchone()
    return Policy(**row) if row else None


def list_policies(conn: sqlite3.Connection) -> list[Policy]:
    return [Policy(**row) for row in conn.execute("SELECT * FROM policies ORDER BY id")]


def insert_version(
    conn: sqlite3.Connection, policy_id: int, text: str
) -> PolicyVersion:
    """Create the next version (1..n) of a policy as a draft."""
    (last,) = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM policy_versions WHERE policy_id = ?",
        (policy_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO policy_versions (policy_id, version, text, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (policy_id, last + 1, text, VersionStatus.DRAFT, utc_now_iso()),
    )
    return get_version(conn, policy_id, last + 1)


def get_version(
    conn: sqlite3.Connection, policy_id: int, version: int
) -> PolicyVersion | None:
    row = conn.execute(
        "SELECT * FROM policy_versions WHERE policy_id = ? AND version = ?",
        (policy_id, version),
    ).fetchone()
    return _version(row) if row else None


def list_versions(conn: sqlite3.Connection, policy_id: int) -> list[PolicyVersion]:
    rows = conn.execute(
        "SELECT * FROM policy_versions WHERE policy_id = ? ORDER BY version",
        (policy_id,),
    )
    return [_version(row) for row in rows]


def get_active_version(
    conn: sqlite3.Connection, policy_id: int
) -> PolicyVersion | None:
    row = conn.execute(
        "SELECT * FROM policy_versions WHERE policy_id = ? AND status = ?",
        (policy_id, VersionStatus.ACTIVE),
    ).fetchone()
    return _version(row) if row else None


def set_version_status(
    conn: sqlite3.Connection,
    policy_id: int,
    version: int,
    status: VersionStatus,
    *,
    compile_error: str | None = None,
    compile_meta: dict[str, Any] | None = None,
) -> None:
    """Set the status; `compile_error`/`compile_meta` are overwritten (None clears them)."""
    conn.execute(
        "UPDATE policy_versions SET status = ?, compile_error = ?, compile_meta = ?"
        " WHERE policy_id = ? AND version = ?",
        (
            status,
            compile_error,
            json.dumps(compile_meta) if compile_meta is not None else None,
            policy_id,
            version,
        ),
    )


def retire_active_version(conn: sqlite3.Connection, policy_id: int) -> None:
    conn.execute(
        "UPDATE policy_versions SET status = ? WHERE policy_id = ? AND status = ?",
        (VersionStatus.RETIRED, policy_id, VersionStatus.ACTIVE),
    )


def _version(row: sqlite3.Row) -> PolicyVersion:
    data = dict(row)
    if data["compile_meta"] is not None:
        data["compile_meta"] = json.loads(data["compile_meta"])
    return PolicyVersion(**data)

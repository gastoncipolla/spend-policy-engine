"""Repository: idempotency records for `POST /expenses` (SPEC §6)."""

import json
import sqlite3
from typing import Any

from covered.store.db import utc_now_iso
from covered.store.records import IdempotencyRecord


def get_record(conn: sqlite3.Connection, key: str) -> IdempotencyRecord | None:
    row = conn.execute(
        "SELECT * FROM idempotency_records WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    return IdempotencyRecord(
        key=row["key"],
        request_hash=row["request_hash"],
        status_code=row["status_code"],
        response=json.loads(row["response"]),
        created_at=row["created_at"],
    )


def insert_record(
    conn: sqlite3.Connection,
    key: str,
    request_hash: str,
    status_code: int,
    response: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO idempotency_records (key, request_hash, status_code, response, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (key, request_hash, status_code, json.dumps(response), utc_now_iso()),
    )

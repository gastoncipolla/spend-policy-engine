"""SQLite connection, migrations and transactions (stdlib sqlite3).

Connections run in autocommit mode (`isolation_level=None`); every write goes
through `transaction`, which issues an explicit BEGIN/COMMIT.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

DEFAULT_DB_PATH = "./data/covered.db"
MEMORY = ":memory:"
BUSY_TIMEOUT_SECONDS = 5.0


def resolve_db_path(db_path: str | os.PathLike[str] | None = None) -> str:
    """Explicit path, else env `COVERED_DB`, else `./data/covered.db`. Creates the folder."""
    path = str(db_path or os.environ.get("COVERED_DB") or DEFAULT_DB_PATH)
    if path != MEMORY:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
        check_same_thread=False,
        timeout=BUSY_TIMEOUT_SECONDS,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_database(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Resolve the path, connect and apply pending migrations."""
    conn = connect(resolve_db_path(db_path))
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every `migrations/*.sql` not applied yet, in name order. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations"
        " (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        row["name"] for row in conn.execute("SELECT name FROM schema_migrations")
    }
    scripts = sorted(
        (item for item in (resources.files("covered.store") / "migrations").iterdir()),
        key=lambda item: item.name,
    )
    newly_applied = []
    for script in scripts:
        if not script.name.endswith(".sql") or script.name in applied:
            continue
        with transaction(conn, immediate=True):
            for statement in _statements(script.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (script.name, utc_now_iso()),
            )
        newly_applied.append(script.name)
    return newly_applied


def _statements(sql: str) -> Iterator[str]:
    """Split a migration into statements so it runs inside one transaction."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer.strip()
            buffer = ""
    if buffer.strip():
        raise ValueError("migration ends with an incomplete statement")


@contextmanager
def transaction(
    conn: sqlite3.Connection, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """One transaction. `immediate=True` takes the write lock up front (BEGIN IMMEDIATE)."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def utc_now_iso() -> str:
    return to_utc_iso(datetime.now(UTC))


def to_utc_iso(moment: datetime) -> str:
    """Fixed-width UTC text, so text comparison matches time order."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")

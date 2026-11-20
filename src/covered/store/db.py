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
    pending = [
        script
        for script in scripts
        if script.name.endswith(".sql") and script.name not in applied
    ]
    if not pending:
        return []
    # SQLite's table-rebuild recipe: foreign keys off while a migration drops
    # and renames tables (the pragma is a no-op inside a transaction), then
    # every foreign key is checked before the migration commits.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for script in pending:
            with transaction(conn, immediate=True):
                execute_script(conn, script.read_text(encoding="utf-8"))
                _require_foreign_keys(conn, script.name)
                conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (script.name, utc_now_iso()),
                )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return [script.name for script in pending]


def execute_script(conn: sqlite3.Connection, sql: str) -> None:
    """Run a multi-statement SQL file on `conn`, inside the caller's transaction.

    `sqlite3.executescript` would commit first, so statements run one by one.
    """
    for statement in _statements(sql):
        conn.execute(statement)


def _require_foreign_keys(conn: sqlite3.Connection, name: str) -> None:
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        rows = ", ".join(f"{row[0]} rowid {row[1]} -> {row[2]}" for row in violations)
        raise sqlite3.IntegrityError(f"{name}: foreign key violations: {rows}")


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

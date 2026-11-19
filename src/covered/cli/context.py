"""Shared CLI plumbing: the database connection and user-facing errors."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

import typer
from pydantic import ValidationError

from covered.domain.errors import CoveredError
from covered.store.db import open_database, resolve_db_path


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    """Open `COVERED_DB` (default ./data/covered.db); print errors, exit 1."""
    conn = open_database(resolve_db_path())
    try:
        yield conn
    except CoveredError as exc:
        fail(f"{exc.code}: {exc.message}")
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}"
            for e in exc.errors()
        )
        fail(f"validation_error: {details}")
    finally:
        conn.close()


def fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)

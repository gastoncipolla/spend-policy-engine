"""FastAPI app factory (SPEC §7)."""

import os

from fastapi import FastAPI

from covered.api.errors import install_error_handlers
from covered.api.routes import catalog, expenses, policies
from covered.services.compilation import Compiler, unconfigured_compiler
from covered.store.db import open_database, resolve_db_path


def create_app(
    db_path: str | os.PathLike[str] | None = None, compiler: Compiler | None = None
) -> FastAPI:
    """Build the API on a SQLite file (default: env `COVERED_DB`, else ./data/covered.db).

    Each request opens its own connection, so `db_path` must be a file, not
    ":memory:". `compiler` is called by `POST .../compile`; without one,
    compiling fails with "compiler not configured".
    """
    app = FastAPI(title="Covered", summary="Will this expense be covered?")
    app.state.db_path = resolve_db_path(db_path)
    app.state.compiler = compiler or unconfigured_compiler
    open_database(app.state.db_path).close()  # apply migrations once, up front

    install_error_handlers(app)
    app.include_router(catalog.router)
    app.include_router(policies.router)
    app.include_router(expenses.router)
    return app

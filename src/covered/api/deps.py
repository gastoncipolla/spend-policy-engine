"""Request dependencies: one SQLite connection per request, the injected compiler."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from covered.services.compilation import Compiler
from covered.store.db import connect


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_compiler(request: Request) -> Compiler:
    return request.app.state.compiler


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
InjectedCompiler = Annotated[Compiler, Depends(get_compiler)]

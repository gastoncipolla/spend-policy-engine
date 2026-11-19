"""Request dependencies: one SQLite connection per request, the acting user
(from `Authorization: Bearer <token>`), the injected compiler."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request

from covered.services import employees
from covered.services.authz import Actor
from covered.services.compilation import Compiler
from covered.store.db import connect


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def bearer_token(authorization: str | None) -> str | None:
    """The token of an `Authorization: Bearer <token>` header, else None."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def get_actor(
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    authorization: Annotated[str | None, Header()] = None,
) -> Actor:
    """401 `unauthenticated` when the header is missing or the token is unknown."""
    return employees.authenticate(conn, bearer_token(authorization))


def get_compiler(request: Request) -> Compiler:
    return request.app.state.compiler


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
InjectedCompiler = Annotated[Compiler, Depends(get_compiler)]

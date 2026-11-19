"""Request id and catch-all error handler, as one ASGI middleware (SPEC §12b).

The request id comes from a valid incoming `X-Request-ID` or is generated. It is
returned in the `X-Request-ID` response header and set in a context variable,
so every log event of the request carries it. An exception no handler turned
into a response is logged with its stack trace and becomes a 500 in the
standard envelope. It lives here, not in `exception_handler(Exception)`,
because Starlette runs that handler outside every middleware, where the
request id is already gone.
"""

import logging
import re
import traceback
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from covered.api.errors import error_response
from covered.services.events import log_event, request_id_var

HEADER = "X-Request-ID"
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
"""Anything else (too long, spaces, control characters) is replaced, so a
client cannot inject arbitrary text into our logs or response headers."""


def incoming_request_id(scope: Scope) -> str | None:
    value = Headers(scope=scope).get(HEADER)
    return value if value and VALID_REQUEST_ID.fullmatch(value) else None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            log_event(
                "unhandled_error",
                level=logging.ERROR,
                method=scope["method"],
                path=scope["path"],
                error=repr(exc),
                traceback=traceback.format_exc(),
            )
            if started:  # too late for a 500: the status line is already sent
                raise
            response = error_response(
                500,
                "internal_error",
                "unexpected error; quote the request id when reporting it",
                request_id=request_id,
            )
            await response(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)

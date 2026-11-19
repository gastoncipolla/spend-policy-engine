"""CSRF protection for the cookie-authenticated pages.

The pages authenticate with a cookie, so a malicious site could try to make the
browser POST a form here (e.g. "approve expense 3") with that cookie attached.
Two layers stop it:

1. The cookie is `SameSite=Lax`: browsers do not send it on cross-site POSTs.
2. This middleware rejects unsafe requests that a browser marks as cross-site,
   using Fetch Metadata (`Sec-Fetch-Site`) or, as a fallback, `Origin`.

Requests authenticated with `Authorization: Bearer` (the JSON API) are not
exposed to CSRF, because browsers never attach that header on their own.
Requests without these headers come from non-browser clients (curl, tests).
"""

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_FETCH_SITES = {"same-origin", "none"}


class CsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _is_cross_site_write(scope):
            body = json.dumps(
                {"error": "forbidden", "message": "cross-site request blocked"}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def _is_cross_site_write(scope: Scope) -> bool:
    if scope["method"] in SAFE_METHODS:
        return False
    headers = {
        name.decode().lower(): value.decode() for name, value in scope["headers"]
    }
    if headers.get("authorization", "").lower().startswith("bearer "):
        return False
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in ALLOWED_FETCH_SITES
    origin = headers.get("origin")
    if origin is not None:
        return urlsplit(origin).netloc != headers.get("host")
    return False

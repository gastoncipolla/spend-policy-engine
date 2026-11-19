"""Structured JSON log events (SPEC §10). No PII beyond fictional employee ids.

Inside an HTTP request every event carries that request's id (SPEC §12b).
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("covered")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
"""Set by the API middleware for the duration of one request."""


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    request_id = request_id_var.get()
    if request_id is not None:
        fields["request_id"] = request_id
    payload = json.dumps({"event": event, **fields}, default=str, sort_keys=True)
    logger.log(level, payload)


def configure_logging(level: int = logging.INFO) -> None:
    """Print the `covered` events as one JSON object per line on stderr.

    Idempotent: calling it twice does not duplicate lines.
    """
    if any(getattr(h, "_covered", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._covered = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

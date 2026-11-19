"""Structured JSON log events (SPEC §10). No PII beyond fictional employee ids."""

import json
import logging
import sys
from typing import Any

logger = logging.getLogger("covered")


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


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

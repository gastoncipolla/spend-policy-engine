"""Structured JSON log events (SPEC §10). No PII beyond fictional employee ids."""

import json
import logging
from typing import Any

logger = logging.getLogger("covered")


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))

"""Company configuration (SPEC §2: config, not a table)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from covered.domain.money import CURRENCY

COMPANY_CURRENCY = CURRENCY
COMPANY_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def utc_now() -> datetime:
    return datetime.now(UTC)

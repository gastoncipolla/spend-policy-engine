"""Company configuration (SPEC §2: config, not a table)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from covered.domain.errors import InvalidInputError
from covered.domain.money import CURRENCY

COMPANY_CURRENCY = CURRENCY
COMPANY_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_company_time(value: str) -> datetime:
    """ISO 8601 date/time; without an offset it is read in company time."""
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInputError(f"not an ISO date/time: {value!r}") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=COMPANY_TZ)

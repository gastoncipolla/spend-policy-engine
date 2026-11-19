"""Money helpers: integer minor units in, integer minor units out.

Humans type decimals ("80.00"); the system stores `int` cents. Conversion goes
through `Decimal` and never through `float`. Input with more precision than the
currency allows is rejected instead of rounded (never guess).
"""

from decimal import Decimal, InvalidOperation

from covered.domain.errors import InvalidAmountError, UnsupportedCurrencyError

CURRENCY = "USD"
"""The single company currency supported by the MVP."""

MINOR_UNIT_DIGITS = 2
_MINOR_PER_MAJOR = 10**MINOR_UNIT_DIGITS

# SPEC-QUESTION: the spec sets no upper bound on amounts. JSON ints are unbounded
# but SQLite INTEGER is 64-bit, so a huge amount would crash at insert (or in a
# SUM). We cap at USD 10 billion: far above any real expense or limit, and far
# below 2**63 even when summed over millions of expenses.
MAX_AMOUNT_MINOR = 10**12
"""Largest accepted amount in minor units (inclusive)."""


def parse_amount(value: str | Decimal | int) -> int:
    """Convert a human amount in major units (e.g. "80.00") to positive minor units (8000).

    Raises `InvalidAmountError` for floats, non-numbers, non-positive amounts,
    amounts above `MAX_AMOUNT_MINOR` and amounts with more than two decimals.
    """
    if isinstance(value, bool | float):
        raise InvalidAmountError(
            f"Amount must be a decimal string, not {type(value).__name__}"
        )
    try:
        amount = Decimal(value.strip()) if isinstance(value, str) else Decimal(value)
    except InvalidOperation:
        raise InvalidAmountError(f"Not a valid amount: {value!r}") from None
    if not amount.is_finite():
        raise InvalidAmountError(f"Not a valid amount: {value!r}")
    minor = amount * _MINOR_PER_MAJOR
    if minor != minor.to_integral_value():
        raise InvalidAmountError(
            f"Amount {value!r} has more than {MINOR_UNIT_DIGITS} decimal places"
        )
    if minor <= 0:
        raise InvalidAmountError(f"Amount must be greater than zero: {value!r}")
    if minor > MAX_AMOUNT_MINOR:
        raise InvalidAmountError(f"Amount is too large: {value!r}")
    return int(minor)


def format_minor(amount_minor: int) -> str:
    """Render minor units as a plain decimal string: 8000 -> "80.00"."""
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(amount_minor), _MINOR_PER_MAJOR)
    return f"{sign}{major}.{minor:0{MINOR_UNIT_DIGITS}d}"


def format_money(amount_minor: int) -> str:
    """Render minor units with the currency code: 8000 -> "USD 80.00"."""
    return f"{CURRENCY} {format_minor(amount_minor)}"


def ensure_supported_currency(currency: str) -> str:
    """Return `currency` if it is the company currency, else raise `UnsupportedCurrencyError`."""
    if currency != CURRENCY:
        raise UnsupportedCurrencyError(
            f"Unsupported currency {currency!r}: only {CURRENCY} is supported"
        )
    return currency

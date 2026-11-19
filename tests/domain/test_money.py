from decimal import Decimal

import pytest

from covered.domain.errors import InvalidAmountError, UnsupportedCurrencyError
from covered.domain.money import (
    ensure_supported_currency,
    format_minor,
    format_money,
    parse_amount,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("80.00", 8000),
        ("80", 8000),
        ("0.01", 1),
        (" 12.5 ", 1250),
        (Decimal("199.99"), 19999),
        (3, 300),
        ("1e2", 10000),
    ],
)
def test_parse_amount_converts_to_minor_units(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw", ["80.001", "0", "-5", "abc", "", "NaN", "Infinity", 80.0, True]
)
def test_parse_amount_rejects_invalid_input(raw):
    with pytest.raises(InvalidAmountError):
        parse_amount(raw)


def test_invalid_amount_error_is_a_validation_error():
    with pytest.raises(InvalidAmountError) as error:
        parse_amount("1.234")
    assert error.value.code == "validation_error"


@pytest.mark.parametrize(
    ("minor", "expected"), [(8000, "80.00"), (1, "0.01"), (0, "0.00"), (-150, "-1.50")]
)
def test_format_minor(minor, expected):
    assert format_minor(minor) == expected


def test_format_money_includes_currency():
    assert format_money(9000) == "USD 90.00"


def test_round_trip_parse_and_format():
    assert format_minor(parse_amount("1234.56")) == "1234.56"


def test_only_company_currency_is_supported():
    assert ensure_supported_currency("USD") == "USD"
    with pytest.raises(UnsupportedCurrencyError):
        ensure_supported_currency("EUR")

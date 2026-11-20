"""Amount literals: separators, money rules and the anti-hallucination check."""

import pytest

from covered.domain.errors import InvalidAmountError
from covered.intake.amounts import (
    AmountNotInText,
    appears_in_text,
    literal_amount,
    to_decimal_string,
)


@pytest.mark.parametrize(
    ("typed", "normalized"),
    [
        ("120", "120"),
        ("45.50", "45.50"),
        ("45,5", "45.5"),
        ("1.500", "1500"),
        ("1,500", "1500"),
        ("1,234.50", "1234.50"),
        ("1.234,50", "1234.50"),
        ("1,234,567", "1234567"),
        ("12.500,00", "12500.00"),
    ],
)
def test_typed_numbers_are_normalized(typed, normalized):
    assert to_decimal_string(typed) == normalized


@pytest.mark.parametrize("typed", ["1.234.5", "12,34,56", "abc", "1.2345", "", "-5"])
def test_malformed_numbers_are_rejected(typed):
    with pytest.raises(ValueError):
        to_decimal_string(typed)


def test_amount_must_appear_as_a_whole_number_in_the_text():
    text = "Uber to the airport, USD 120 and a 1.234,50 hotel"
    assert appears_in_text("120", text)
    assert appears_in_text("1.234,50", text)
    assert not appears_in_text("12", text)  # part of 120
    assert not appears_in_text("234", text)  # part of 1.234,50
    assert not appears_in_text("1.234", text)  # 1.234,50 continues


def test_literal_amount_uses_the_money_rules():
    assert literal_amount("1.234,50", "hotel 1.234,50 USD") == 123450
    with pytest.raises(AmountNotInText):
        literal_amount("35000", "un almuerzo de 35 lucas")  # expanded by the model
    with pytest.raises(InvalidAmountError):
        literal_amount("0", "taxi 0 USD")

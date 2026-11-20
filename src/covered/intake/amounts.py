"""Amounts as people type them: "120", "45.50", "1,234.50", "1.234,50".

`literal_amount` turns the provider's `amount_text` into minor units, but only
if that exact number appears in the employee's text as a whole number token
(the anti-hallucination check, like the compiler's clause citation). The
conversion itself goes through `parse_amount`, so the domain money rules
(positive, at most two decimals, upper bound) apply unchanged.
"""

import re

from covered.domain.money import parse_amount

_GROUPED = {
    ".": re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"),
    ",": re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"),
}
_PLAIN = re.compile(r"\d+(?:[.,]\d{1,2})?")


class AmountNotInText(ValueError):
    """The number is not literally in the text: the provider made it up."""


def to_decimal_string(amount_text: str) -> str:
    """Normalize a typed number to "1234.50". Raises ValueError if it is not one.

    One separator followed by exactly three digits is a thousands separator
    ("1.500" and "1,500" are both 1500); a separator followed by one or two
    digits is the decimal point. With both, the last one is the decimal point.
    """
    text = amount_text.strip()
    if _PLAIN.fullmatch(text):
        return text.replace(",", ".")
    for thousands, pattern in _GROUPED.items():
        if pattern.fullmatch(text):
            decimal_mark = "," if thousands == "." else "."
            integer, _, decimals = text.partition(decimal_mark)
            digits = integer.replace(thousands, "")
            return f"{digits}.{decimals}" if decimals else digits
    raise ValueError(f"not a number: {amount_text!r}")


def appears_in_text(amount_text: str, text: str) -> bool:
    """`amount_text` occurs in `text` and is not part of a longer number."""
    pattern = rf"(?<![\d.,]){re.escape(amount_text.strip())}(?![\d]|[.,]\d)"
    return re.search(pattern, text) is not None


def literal_amount(amount_text: str, text: str) -> int:
    """Minor units of `amount_text`, which must appear verbatim in `text`.

    Raises `AmountNotInText`, or the domain `InvalidAmountError` / ValueError
    for something that is not a valid positive amount.
    """
    if not amount_text.strip() or not appears_in_text(amount_text, text):
        raise AmountNotInText(amount_text)
    return parse_amount(to_decimal_string(amount_text))

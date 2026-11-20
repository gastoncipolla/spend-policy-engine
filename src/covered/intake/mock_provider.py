"""Offline intake provider: a small deterministic keyword/regex reader.

It exists so the feature works without an API key and in CI. It is deliberately
simple (it does not understand language) and emits the same `IntakePayload` as
the real provider, so the same validation runs on both.
"""

import re
import unicodedata

from covered.domain import Category
from covered.intake.prompt import PROMPT_VERSION
from covered.intake.result import IntakeMeta, IntakeReply
from covered.intake.schema import DateKind, IntakePayload

CATEGORY_WORDS: dict[Category, tuple[str, ...]] = {
    Category.MEALS: (
        "cena", "almuerzo", "desayuno", "comida", "merienda", "cafe",
        "dinner", "lunch", "breakfast", "meal", "coffee", "restaurant",
    ),
    Category.GROUND_TRANSPORT: (
        "uber", "taxi", "cabify", "remis", "colectivo", "subte", "tren",
        "train", "bus", "cab", "rideshare",
    ),
    Category.LODGING: ("hotel", "hostel", "airbnb", "alojamiento", "lodging"),
    Category.AIRFARE: ("vuelo", "avion", "pasaje aereo", "flight", "airfare"),
    Category.SOFTWARE: ("software", "licencia", "suscripcion", "subscription", "saas"),
    Category.TRAINING: ("curso", "capacitacion", "course", "training", "conferencia",
                        "conference"),
    Category.ENTERTAINMENT: ("teatro", "cine", "concierto", "theater", "cinema",
                             "concert", "show"),
    Category.ALCOHOL: ("vino", "cerveza", "wine", "beer", "bar"),
}  # fmt: skip

CURRENCY_WORDS: dict[str, tuple[str, ...]] = {
    "USD": ("usd", "us$", "u$s", "dolares", "dollars", "dollar"),
    "ARS": ("ars", "pesos", "lucas"),
    "EUR": ("eur", "euros", "euro", "€"),
}

WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4,
    "sabado": 5, "domingo": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
    "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}  # fmt: skip

RELATIVE_DAYS = {
    "anteayer": -2, "antes de ayer": -2, "day before yesterday": -2,
    "ayer": -1, "yesterday": -1, "hoy": 0, "today": 0,
    "manana": 1, "tomorrow": 1,
}  # fmt: skip

MERCHANTS = ("Uber", "Cabify", "Starbucks", "Airbnb", "Despegar", "Aerolíneas")

_NUMBER = re.compile(
    r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
)
_DAYS_AGO = re.compile(r"(?:hace (\d+) dias|(\d+) days ago)")
_CALENDAR = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
_CLOCK = re.compile(
    r"\b(\d{1,2}):(\d{2})\b|\ba las (\d{1,2})\b|\bat (\d{1,2}) ?(am|pm)\b"
)


def fold(text: str) -> str:
    """Lowercase without accents: "Miércoles" -> "miercoles"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _first_match(folded: str, table: dict) -> object | None:
    """The key whose word appears first in `folded` (whole words only)."""
    best = None
    for key, words in table.items():
        for word in words:
            found = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", folded)
            if found and (best is None or found.start() < best[0]):
                best = (found.start(), key)
    return best[1] if best else None


class MockIntakeProvider:
    name = "mock"

    def read(self, text: str) -> IntakeReply:
        meta = IntakeMeta(
            provider=self.name,
            model="mock",
            prompt_version=PROMPT_VERSION,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )
        return IntakeReply(payload=read_payload(text).model_dump_json(), meta=meta)


def read_payload(text: str) -> IntakePayload:
    folded = fold(text)
    without_dates = _DAYS_AGO.sub(" ", _CLOCK.sub(" ", _CALENDAR.sub(" ", folded)))
    amounts = _NUMBER.findall(without_dates)
    category = _first_match(folded, CATEGORY_WORDS)
    merchant = next((name for name in MERCHANTS if fold(name) in folded), None)
    return IntakePayload(
        expense_count=len(amounts) or (1 if category else 0),
        category=category.value if category else None,
        amount_text=amounts[0] if amounts else None,
        currency=_first_match(folded, CURRENCY_WORDS),
        **_date_fields(text, folded),
        time=_clock(folded),
        merchant=merchant,
        description=text.strip()[:80] or None,
        justification=None,
    )


def _date_fields(text: str, folded: str) -> dict:
    empty = {
        "offset_days": None,
        "weekday": None,
        "day": None,
        "month": None,
        "year": None,
    }
    if found := _DAYS_AGO.search(folded):
        days = int(found.group(1) or found.group(2))
        return _date(
            text, found, DateKind.RELATIVE_DAYS, {**empty, "offset_days": -days}
        )
    if found := _CALENDAR.search(folded):
        day, month, year = found.groups()
        fields = {**empty, "day": int(day), "month": int(month),
                  "year": int(year) if year else None}  # fmt: skip
        return _date(text, found, DateKind.CALENDAR_DATE, fields)
    for words, kind, field in (
        (RELATIVE_DAYS, DateKind.RELATIVE_DAYS, "offset_days"),
        (WEEKDAYS, DateKind.PREVIOUS_WEEKDAY, "weekday"),
    ):
        for word, value in words.items():
            if found := re.search(rf"(?<!\w){word}(?!\w)", folded):
                return _date(text, found, kind, {**empty, field: value})
    return {"date_kind": DateKind.NONE, "date_text": None, **empty}


def _date(text: str, found: re.Match, kind: DateKind, fields: dict) -> dict:
    # Folding usually keeps the length ("sábado" -> "sabado"), so the span maps
    # back to `text`; if not, the folded words are used and validation flags them.
    same_length = len(fold(text)) == len(text)
    literal = text[found.start() : found.end()] if same_length else found.group(0)
    return {"date_kind": kind, "date_text": literal, **fields}


def _clock(folded: str) -> str | None:
    found = _CLOCK.search(folded)
    if found is None:
        return None
    hour, minute, spoken, english, half = found.groups()
    if hour is not None:
        return f"{int(hour):02d}:{minute}" if int(hour) < 24 else None
    hour = int(spoken or english)
    if half == "pm" and hour < 12:
        hour += 12
    return f"{hour:02d}:00" if hour < 24 else None

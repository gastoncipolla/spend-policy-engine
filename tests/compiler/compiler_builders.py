"""Small builders shared by the compiler tests (imported as a plain module)."""

import json

from covered.compiler import CompileMeta, ProviderReply

POLICY = """\
Meals are reimbursed up to USD 80.00 per expense.
Alcohol is not reimbursable.
Book economy class unless the flight
is longer than 8 hours.
"""

MEALS_CLAUSE = "Meals are reimbursed up to USD 80.00 per expense."
ALCOHOL_CLAUSE = "Alcohol is not reimbursable."
ECONOMY_CLAUSE = "Book economy class unless the flight is longer than 8 hours."


def max_meals(amount_minor=8000, clause=MEALS_CLAUSE) -> dict:
    return {
        "clause": clause,
        "params": {
            "type": "max_amount",
            "category": "meals",
            "amount_minor": amount_minor,
        },
    }


def no_alcohol() -> dict:
    return {
        "clause": ALCOHOL_CLAUSE,
        "params": {"type": "prohibited_category", "category": "alcohol"},
    }


def economy() -> dict:
    return {
        "clause": ECONOMY_CLAUSE,
        "reason": "Fare class is not part of the expense data.",
        "categories": ["airfare"],
        "effect": "requires_review",
    }


class StaticProvider:
    """Provider that returns a fixed payload (dict -> JSON, or raw text)."""

    name = "static"

    def __init__(self, payload: dict | str) -> None:
        self.payload = payload if isinstance(payload, str) else json.dumps(payload)

    def propose(self, text: str) -> ProviderReply:
        meta = CompileMeta(provider=self.name, model="static", prompt_version="test")
        return ProviderReply(payload=self.payload, meta=meta)

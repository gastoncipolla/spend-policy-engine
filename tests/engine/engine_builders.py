"""Small builders shared by the engine tests (imported as a plain module)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from covered.domain import CompiledPolicy, ExpenseInput, PolicyRule

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
WEDNESDAY_NOON = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)


def expense(**overrides) -> ExpenseInput:
    fields = {
        "employee_id": "ana",
        "amount_minor": 5000,
        "category": "meals",
        "occurred_at": WEDNESDAY_NOON,
    }
    return ExpenseInput(**(fields | overrides))


def rule(rule_id: int, **params) -> PolicyRule:
    return PolicyRule(id=rule_id, clause=f"clause {rule_id}", params=params)


def policy(*rules: PolicyRule, uncompilable=()) -> CompiledPolicy:
    return CompiledPolicy(
        policy_id=1, version=1, rules=list(rules), uncompilable=list(uncompilable)
    )

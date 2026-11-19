"""Stored entities as the store returns them (SPEC §2).

These are read models: repositories build them from rows, services and the API
return them. Statuses that only exist once things are persisted live here.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict

from covered.domain import Category, RuleParams, RuleType, UncompilableEffect


class VersionStatus(StrEnum):
    DRAFT = "draft"
    COMPILING = "compiling"
    COMPILE_FAILED = "compile_failed"
    ACTIVE = "active"
    RETIRED = "retired"


class RuleStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class RuleOrigin(StrEnum):
    LLM = "llm"
    MANUAL = "manual"


class UncompilableStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class ExpenseStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


CONFLICT_FLAG = "conflict"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Policy(_Record):
    id: int
    name: str


class Employee(_Record):
    id: str
    name: str
    policy_id: int | None


class PolicyVersion(_Record):
    policy_id: int
    version: int
    text: str
    status: VersionStatus
    compile_error: str | None = None
    compile_meta: dict[str, Any] | None = None
    created_at: datetime


class StoredRule(_Record):
    id: int
    policy_id: int
    version: int
    type: RuleType
    params: RuleParams
    clause: str
    status: RuleStatus
    origin: RuleOrigin
    flags: list[str] = []


class StoredUncompilable(_Record):
    id: int
    policy_id: int
    version: int
    clause: str
    reason: str
    categories: list[str]
    """Catalog category codes, or `["*"]`."""
    effect: UncompilableEffect
    status: UncompilableStatus


class StoredExpense(_Record):
    id: int
    employee_id: str
    amount_minor: int
    currency: str
    category: Category
    merchant: str | None
    occurred_at: AwareDatetime
    justification: str | None
    pre_approval_id: str | None
    status: ExpenseStatus
    created_at: AwareDatetime


class IdempotencyRecord(_Record):
    key: str
    request_hash: str
    status_code: int
    response: dict[str, Any]
    created_at: AwareDatetime

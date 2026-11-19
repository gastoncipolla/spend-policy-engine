"""The engine's output: an outcome plus every reason and warning behind it."""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator


class Outcome(StrEnum):
    APPROVED = "approved"
    NEEDS_APPROVAL = "needs_approval"
    REJECTED = "rejected"


OUTCOME_PRECEDENCE: dict[Outcome, int] = {
    Outcome.APPROVED: 0,
    Outcome.NEEDS_APPROVAL: 1,
    Outcome.REJECTED: 2,
}
"""rejected > needs_approval > approved (SPEC §4.2)."""


class ReasonSource(StrEnum):
    RULE = "rule"
    UNCOMPILABLE = "uncompilable"
    UNCOVERED_CATEGORY = "uncovered_category"


class Reason(BaseModel):
    """Why an expense is not simply approved.

    Exactly one source: a rule (`rule_id`), an uncompilable clause
    (`uncompilable_id`), or the uncovered-category check (no id, no clause).
    """

    # SPEC-QUESTION: §2 says a Reason has `rule_id | uncompilable_id` and a
    # clause, but the uncovered-category reason (§4.2) has neither. We add an
    # explicit `source` and allow `clause = None` only for that case.

    model_config = ConfigDict(frozen=True)

    source: ReasonSource
    rule_id: int | None = None
    uncompilable_id: int | None = None
    clause: str | None = None
    outcome: Literal[Outcome.NEEDS_APPROVAL, Outcome.REJECTED]
    message: str

    @model_validator(mode="after")
    def _source_matches_fields(self) -> "Reason":
        expected = {
            ReasonSource.RULE: (True, False, True),
            ReasonSource.UNCOMPILABLE: (False, True, True),
            ReasonSource.UNCOVERED_CATEGORY: (False, False, False),
        }[self.source]
        actual = (
            self.rule_id is not None,
            self.uncompilable_id is not None,
            self.clause is not None,
        )
        if actual != expected:
            raise ValueError(f"fields do not match reason source {self.source}")
        return self


class DecisionWarning(BaseModel):
    """An informational uncompilable clause that applies to the expense."""

    model_config = ConfigDict(frozen=True)

    uncompilable_id: int
    clause: str
    message: str


class Decision(BaseModel):
    """Result of evaluating one expense against one policy version.

    `expense_id` is filled by the caller once the expense is stored (it stays
    `None` for checks).
    """

    model_config = ConfigDict(frozen=True)

    expense_id: int | None = None
    employee_id: str
    policy_id: int
    policy_version: int
    outcome: Outcome
    reasons: list[Reason]
    warnings: list[DecisionWarning]
    evaluated_at: AwareDatetime

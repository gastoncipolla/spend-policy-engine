"""What a single rule check returns when it does not pass."""

from dataclasses import dataclass
from typing import Literal

from covered.domain import Outcome


@dataclass(frozen=True)
class Finding:
    """A non-pass rule result. Rule checks return `None` for pass."""

    outcome: Literal[Outcome.NEEDS_APPROVAL, Outcome.REJECTED]
    message: str


def rejected(message: str) -> Finding:
    return Finding(Outcome.REJECTED, message)


def needs_approval(message: str) -> Finding:
    return Finding(Outcome.NEEDS_APPROVAL, message)

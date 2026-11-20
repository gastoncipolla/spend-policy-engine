"""`POST /expenses/parse`: a sentence in, a draft expense out ("Ask Covered").

Any authenticated user may call it (it only reads their own sentence). It does
not evaluate, store or consume anything: the draft goes back to the client,
which sends the confirmed expense to `POST /expenses/check` or `/expenses`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from covered.api.deps import CurrentActor
from covered.intake import (
    MAX_TEXT_LENGTH,
    IntakeProvider,
    IntakeResult,
    get_intake_provider,
    parse_expense_text,
)
from covered.services.config import COMPANY_TZ, utc_now

router = APIRouter(tags=["expenses"])


class ParseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]


def intake_provider(request: Request) -> IntakeProvider:
    """`app.state.intake_provider` if set (tests), else chosen once from the env."""
    state = request.app.state
    if getattr(state, "intake_provider", None) is None:
        state.intake_provider = get_intake_provider()
    return state.intake_provider


InjectedIntakeProvider = Annotated[IntakeProvider, Depends(intake_provider)]


@router.post("/expenses/parse")
def parse_expense(
    body: ParseBody, actor: CurrentActor, provider: InjectedIntakeProvider
) -> IntakeResult:
    """Draft + `missing` + `flags` + provider/model. Never a decision."""
    return parse_expense_text(body.text, provider, now=utc_now(), tz=COMPANY_TZ)

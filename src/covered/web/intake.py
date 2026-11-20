"""Page route for "Ask Covered": `POST /employee/interpret`.

The employee types a sentence; the result is the usual employee page with the
check form prefilled from the draft and the flags shown above it. Nothing is
evaluated here: the employee reviews the form and presses the usual
"Will this be covered?" button.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from covered.api.deps import Conn
from covered.api.routes.intake import InjectedIntakeProvider
from covered.domain import Category
from covered.domain.errors import CoveredError
from covered.domain.money import format_minor
from covered.intake import IntakeResult, parse_expense_text
from covered.services.config import COMPANY_TZ, utc_now
from covered.web import pages

router = APIRouter(include_in_schema=False)


def draft_form(result: IntakeResult) -> dict[str, str]:
    """The check form's fields from a draft. Missing amount/date stay empty
    (the form requires them); a missing category becomes "other", which never
    auto-approves (SPEC §4.2) and is flagged on the page."""
    draft = result.draft
    occurred_at = draft.occurred_at
    return {
        "amount": format_minor(draft.amount_minor) if draft.amount_minor else "",
        "category": (draft.category or Category.OTHER).value,
        "occurred_at": occurred_at.astimezone(COMPANY_TZ).strftime("%Y-%m-%dT%H:%M")
        if occurred_at
        else "",
        "merchant": draft.merchant or "",
        "justification": draft.justification or "",
        "pre_approval_id": "",
    }


@router.post("/employee/interpret", response_class=HTMLResponse)
def interpret(
    request: Request,
    conn: Conn,
    provider: InjectedIntakeProvider,
    text: Annotated[str, Form()] = "",
) -> HTMLResponse:
    actor = pages._actor(request, conn)
    if actor is None:
        return pages._employee(request, conn, None, error=pages.CHOOSE_USER)
    try:
        result = parse_expense_text(text, provider, now=utc_now(), tz=COMPANY_TZ)
    except CoveredError as exc:
        return pages._employee(
            request, conn, actor, error=exc.message, intake_text=text
        )
    return pages._employee(
        request,
        conn,
        actor,
        form=draft_form(result),
        intake=result,
        intake_text=text,
    )

"""Server-rendered pages (SPEC §8): `/`, `/employee`, `/finance`.

Pages call the same services as the API. Form posts on /finance redirect back
(post/redirect/get); the employee form renders its decision directly, and its
hidden idempotency key makes a browser re-post a harmless replay.
"""

import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from covered.api.deps import Conn, InjectedCompiler
from covered.domain import CATEGORY_NAMES, Decision, ExpenseInput, UncompilableEffect
from covered.domain.errors import CoveredError, NotFoundError
from covered.domain.money import format_money, parse_amount
from covered.services import employees, expenses, policies
from covered.services.compilation import compile_version
from covered.services.config import COMPANY_TZ, parse_company_time, utc_now
from covered.services.describe import OUTCOME_LABELS, categories_text, describe_rule
from covered.store.records import ExpenseStatus, RuleStatus
from covered.web.highlight import highlight_clauses

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["money"] = format_money
templates.env.filters["local_time"] = lambda moment: moment.astimezone(
    COMPANY_TZ
).strftime("%a %Y-%m-%d %H:%M")
templates.env.globals.update(
    outcome_label=lambda outcome: OUTCOME_LABELS[outcome],
    describe_rule=describe_rule,
    categories_text=categories_text,
    categories=CATEGORY_NAMES,
    effects=list(UncompilableEffect),
)


def install(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    for route, method, endpoint in ROUTES:
        app.add_api_route(
            route,
            endpoint,
            methods=[method],
            response_class=HTMLResponse,
            include_in_schema=False,
        )


def _render(request: Request, template: str, **context) -> HTMLResponse:
    context["provider"] = request.app.state.provider_name
    return templates.TemplateResponse(request, template, context)


# Home


def home(request: Request, conn: Conn) -> HTMLResponse:
    return _render(
        request,
        "index.html",
        policies=policies.list_policies(conn),
        employees=employees.list_employees(conn),
    )


# Employee


def employee_page(
    request: Request, conn: Conn, employee_id: str | None = None
) -> HTMLResponse:
    return _employee(request, conn, employee_id)


def employee_post(
    request: Request,
    conn: Conn,
    employee_id: Annotated[str, Form()],
    amount: Annotated[str, Form()],
    category: Annotated[str, Form()],
    occurred_at: Annotated[str, Form()],
    action: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    merchant: Annotated[str, Form()] = "",
    justification: Annotated[str, Form()] = "",
    pre_approval_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    form = {
        "amount": amount,
        "category": category,
        "occurred_at": occurred_at,
        "merchant": merchant,
        "justification": justification,
        "pre_approval_id": pre_approval_id,
    }
    try:
        expense = ExpenseInput(
            employee_id=employee_id,
            amount_minor=parse_amount(amount),
            category=category,
            occurred_at=parse_company_time(occurred_at),
            merchant=merchant or None,
            justification=justification or None,
            pre_approval_id=pre_approval_id or None,
        )
        if action == "submit":
            result = expenses.submit_expense(conn, expense, idempotency_key)
            decision = Decision.model_validate(result.body["decision"])
            submitted = result.body["expense"]["id"]
        else:
            decision, submitted = expenses.check_expense(conn, expense), None
    except (CoveredError, ValidationError) as exc:
        return _employee(request, conn, employee_id, form=form, error=_message(exc))
    return _employee(
        request, conn, employee_id, form=form, decision=decision, submitted=submitted
    )


def _employee(
    request: Request,
    conn: Conn,
    employee_id: str | None,
    *,
    form: dict[str, str] | None = None,
    **context,
) -> HTMLResponse:
    staff = employees.list_employees(conn)
    current = next((e for e in staff if e.id == employee_id), None)
    if current is None and staff:
        current = staff[0]
    history = expenses.list_expenses(conn, employee_id=current.id) if current else []
    now = utc_now().astimezone(COMPANY_TZ).strftime("%Y-%m-%dT%H:%M")
    return _render(
        request,
        "employee.html",
        employees=staff,
        current=current,
        history=history,
        form=form or {"occurred_at": now, "category": "meals"},
        idempotency_key=str(uuid.uuid4()),
        **context,
    )


# Finance


def finance_page(
    request: Request,
    conn: Conn,
    policy_id: int | None = None,
    version: int | None = None,
    error: str | None = None,
    notice: str | None = None,
) -> HTMLResponse:
    summaries = policies.list_policies(conn)
    summary = next((p for p in summaries if p.id == policy_id), None)
    if summary is None and summaries:
        summary = summaries[0]
    detail = None
    if summary is not None and summary.versions:
        number = (
            version
            or summary.active_version
            or max(v.version for v in summary.versions)
        )
        try:
            detail = policies.get_version_detail(conn, summary.id, number)
        except NotFoundError as exc:
            error = exc.message
    labels = {}
    if detail is not None:
        labels.update({rule.clause: f"R{rule.id}" for rule in detail.rules})
        labels.update({item.clause: f"U{item.id}" for item in detail.uncompilable})
    return _render(
        request,
        "finance.html",
        policies=summaries,
        summary=summary,
        detail=detail,
        policy_html=highlight_clauses(detail.text, labels) if detail else "",
        editable=detail is not None and detail.status in ("draft", "compile_failed"),
        pending=expenses.list_expenses(conn, status=ExpenseStatus.PENDING),
        error=error,
        notice=notice,
    )


def _back(policy_id: int, version: int, **message: str) -> RedirectResponse:
    query = urlencode({"policy_id": policy_id, "version": version, **message})
    return RedirectResponse(f"/finance?{query}", status_code=303)


def _attempt(policy_id: int, version: int, action, notice: str) -> RedirectResponse:
    """Run a finance action and redirect back with a notice or the error."""
    try:
        action()
    except (CoveredError, ValidationError) as exc:
        return _back(policy_id, version, error=_message(exc))
    return _back(policy_id, version, notice=notice)


def review_rule(
    conn: Conn,
    rule_id: int,
    status: Annotated[RuleStatus, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        policy_id,
        version,
        lambda: policies.update_rule(conn, rule_id, status=status),
        f"Rule R{rule_id} {status}.",
    )


def classify(
    conn: Conn,
    item_id: int,
    effect: Annotated[UncompilableEffect, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
    categories: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    return _attempt(
        policy_id,
        version,
        lambda: policies.classify_uncompilable(
            conn, item_id, categories=categories or ["*"], effect=effect
        ),
        f"Clause U{item_id} confirmed.",
    )


def compile_draft(
    conn: Conn,
    compiler: InjectedCompiler,
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        policy_id,
        version,
        lambda: compile_version(conn, policy_id, version, compiler),
        "Compiled: review the proposed rules.",
    )


def activate(
    conn: Conn,
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        policy_id,
        version,
        lambda: policies.activate_version(conn, policy_id, version),
        f"Version {version} is now active.",
    )


def new_version(
    conn: Conn,
    policy_id: Annotated[int, Form()],
    text: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        created = policies.create_version(conn, policy_id, text)
    except (CoveredError, ValidationError) as exc:
        return _back(policy_id, 0, error=_message(exc))
    return _back(policy_id, created.version, notice="Draft created: compile it next.")


def resolve(
    conn: Conn,
    expense_id: int,
    resolution: Annotated[ExpenseStatus, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        policy_id,
        version,
        lambda: expenses.resolve_expense(conn, expense_id, resolution),
        f"Expense #{expense_id} {resolution}.",
    )


def _message(exc: Exception) -> str:
    if isinstance(exc, CoveredError):
        return exc.message
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors())
    return str(exc)


ROUTES = [
    ("/", "GET", home),
    ("/employee", "GET", employee_page),
    ("/employee", "POST", employee_post),
    ("/finance", "GET", finance_page),
    ("/finance/rules/{rule_id}", "POST", review_rule),
    ("/finance/uncompilable/{item_id}", "POST", classify),
    ("/finance/compile", "POST", compile_draft),
    ("/finance/activate", "POST", activate),
    ("/finance/versions", "POST", new_version),
    ("/finance/expenses/{expense_id}/resolve", "POST", resolve),
]

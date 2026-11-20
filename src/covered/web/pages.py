"""Server-rendered pages (SPEC §8): `/employee`, `/team`, `/finance`, `/demo`.

Pages call the same services as the API, acting as the user chosen in the demo
panel (`/demo`, SPEC §12a "act as"): the cookie holds that user's demo token,
the same one the API takes as `Authorization: Bearer`. `/` sends you to your
home, or to the demo panel when nobody is signed in. Pages only show what the
user may do, but the services enforce it anyway.

Form posts that change state redirect back (post/redirect/get); the employee
form renders its decision directly, and its hidden idempotency key makes a
browser re-post a harmless replay.
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
from covered.domain.errors import CoveredError, NotFoundError, UnauthenticatedError
from covered.domain.money import format_money, parse_amount
from covered.services import authz, employees, expenses, policies
from covered.services.authz import Actor
from covered.services.compilation import compile_version
from covered.services.config import COMPANY_TZ, parse_company_time, utc_now
from covered.services.describe import OUTCOME_LABELS, categories_text, describe_rule
from covered.store.records import ExpenseStatus, Role, RuleStatus
from covered.web.highlight import highlight_clauses

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["money"] = format_money
# A stored status code in words, e.g. "compile_failed" -> "Compile failed".
templates.env.filters["words"] = lambda code: str(code).replace("_", " ").capitalize()
templates.env.filters["local_time"] = lambda moment: moment.astimezone(
    COMPANY_TZ
).strftime("%a %Y-%m-%d %H:%M")
templates.env.globals.update(
    outcome_label=lambda outcome: OUTCOME_LABELS[outcome],
    describe_rule=describe_rule,
    categories_text=categories_text,
    categories=CATEGORY_NAMES,
    effects=list(UncompilableEffect),
    is_finance=authz.is_finance,
    is_manager=lambda user: Role.MANAGER in user.roles,
    status_label=lambda status: STATUS_LABELS[status],
    role_abilities=lambda user: [ROLE_ABILITIES[r] for r in Role if r in user.roles],
)

# What each status and role means, in words (badges never rely on color alone).
STATUS_LABELS = {
    ExpenseStatus.APPROVED: "Approved",
    ExpenseStatus.PENDING: "Pending approval",
    ExpenseStatus.REJECTED: "Rejected",
}
ROLE_ABILITIES = {  # SPEC §12a permission matrix
    Role.EMPLOYEE: "check and submit own expenses",
    Role.MANAGER: "approve or reject the team's pending expenses (never own)",
    Role.FINANCE: "review rules, activate policies, resolve any expense (never own)",
}

TOKEN_COOKIE = "covered_token"
CHOOSE_USER = "Choose who you are in the demo panel first (Demo mode → Choose a user)."
HOME = "/employee"  # everyone is an employee; role areas are in the top nav
DEMO = "/demo"  # the demo panel: choose who to sign in as (no login)


def _pages_for(actor: Actor) -> list[tuple[str, str]]:
    """The pages this user may open, as (path, nav label): never a link that 403s."""
    pages = [(HOME, "My expenses")]
    if Role.MANAGER in actor.roles:
        pages.append(("/team", "Team approvals"))
    if authz.is_finance(actor):
        pages.append(("/finance", "Finance"))
    return pages


def _team_pending(conn: Conn, actor: Actor) -> list:
    """Pending expenses of the people who report to this manager."""
    if Role.MANAGER not in actor.roles:
        return []
    team = {
        e.id for e in employees.list_employees(conn, actor) if e.manager_id == actor.id
    }
    pending = expenses.list_expenses(conn, actor, status=ExpenseStatus.PENDING)
    return [item for item in pending if item.expense.employee_id in team]


def _waiting_for(conn: Conn, actor: Actor, path: str) -> int | None:
    """How many pending expenses this user can decide on that page (nav badge)."""
    if path == "/team":
        return len(_team_pending(conn, actor))
    if path == "/finance":
        pending = expenses.list_expenses(conn, actor, status=ExpenseStatus.PENDING)
        return sum(item.expense.employee_id != actor.id for item in pending)
    return None


def install(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    for route, method, endpoint in ROUTES:
        app.add_api_route(
            route,
            endpoint,
            methods=[method],
            response_class=HTMLResponse,
            response_model=None,  # some pages redirect instead of rendering
            include_in_schema=False,
        )


def _actor(request: Request, conn: Conn) -> Actor | None:
    """The user behind the "act as" cookie, or None if none (or unknown) is set."""
    try:
        return employees.authenticate(conn, request.cookies.get(TOKEN_COOKIE))
    except UnauthenticatedError:
        return None


def _render(
    request: Request,
    conn: Conn,
    actor: Actor | None,
    template: str,
    *,
    status_code: int = 200,
    **context,
) -> HTMLResponse:
    users = employees.demo_users(conn)
    nav = [
        (path, label, _waiting_for(conn, actor, path))
        for path, label in (_pages_for(actor) if actor else [])
    ]
    context.update(
        provider=request.app.state.provider_name,
        actor=actor,
        users=users,
        names={user.id: user.name for user in users},
        nav=nav,
        here=request.url.path,
    )
    return templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


# Act as (demo identity, no login)


def act_as(
    conn: Conn,
    user_id: Annotated[str, Form()] = "",  # empty: sign out
    next_page: Annotated[str, Form(alias="next")] = "/",
) -> RedirectResponse:
    """Store the chosen demo user's token in a cookie; an unknown user clears it.

    Stay on the same page when the new user may open it, else go to their home.
    """
    token = employees.demo_token(conn, user_id)
    actor = employees.authenticate(conn, token) if token else None
    if actor is None:  # sign out
        response = RedirectResponse(DEMO, status_code=303)
        response.delete_cookie(TOKEN_COOKIE)
        return response
    allowed = [path for path, _ in _pages_for(actor)]
    target = next_page if next_page in allowed else HOME
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="lax")
    return response


# Landing: your home, or the demo panel to choose who you are


def home(request: Request, conn: Conn) -> RedirectResponse:
    target = DEMO if _actor(request, conn) is None else HOME
    return RedirectResponse(target, status_code=303)


def demo_panel(request: Request, conn: Conn) -> HTMLResponse:
    return _render(request, conn, _actor(request, conn), "index.html")


# Employee


def employee_page(
    request: Request,
    conn: Conn,
    error: str | None = None,
    notice: str | None = None,
) -> HTMLResponse | RedirectResponse:
    actor = _actor(request, conn)
    if actor is None:
        return RedirectResponse(DEMO, status_code=303)
    return _employee(request, conn, actor, error=error, notice=notice)


def employee_post(
    request: Request,
    conn: Conn,
    amount: Annotated[str, Form()],
    category: Annotated[str, Form()],
    occurred_at: Annotated[str, Form()],
    action: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    merchant: Annotated[str, Form()] = "",
    justification: Annotated[str, Form()] = "",
    pre_approval_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    actor = _actor(request, conn)
    if actor is None:
        return _employee(request, conn, None, error=CHOOSE_USER)
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
            employee_id=actor.id,
            amount_minor=parse_amount(amount),
            category=category,
            occurred_at=parse_company_time(occurred_at),
            merchant=merchant or None,
            justification=justification or None,
            pre_approval_id=pre_approval_id or None,
        )
        if action == "submit":
            result = expenses.submit_expense(conn, actor, expense, idempotency_key)
            decision = Decision.model_validate(result.body["decision"])
            submitted = result.body["expense"]["id"]
        else:
            decision, submitted = expenses.check_expense(conn, actor, expense), None
    except (CoveredError, ValidationError) as exc:
        return _employee(request, conn, actor, form=form, error=_message(exc))
    return _employee(
        request, conn, actor, form=form, decision=decision, submitted=submitted
    )


def employee_resolve(
    request: Request,
    conn: Conn,
    expense_id: int,
    resolution: Annotated[ExpenseStatus, Form()],
) -> RedirectResponse:
    """A manager resolves a team member's pending expense (back to /team)."""
    message = _try(
        request,
        conn,
        lambda actor: expenses.resolve_expense(conn, actor, expense_id, resolution),
        f"Expense #{expense_id} {resolution}.",
    )
    return RedirectResponse(f"/team?{urlencode(message)}", status_code=303)


def _employee(
    request: Request,
    conn: Conn,
    actor: Actor | None,
    *,
    form: dict[str, str] | None = None,
    **context,
) -> HTMLResponse:
    history, policy, team_waiting = [], None, 0
    if actor is not None:
        team_waiting = len(_team_pending(conn, actor))
        history = expenses.list_expenses(conn, actor, employee_id=actor.id)
        policy = next(
            (p for p in policies.list_policies(conn, actor) if p.id == actor.policy_id),
            None,
        )
    now = utc_now().astimezone(COMPANY_TZ).strftime("%Y-%m-%dT%H:%M")
    return _render(
        request,
        conn,
        actor,
        "employee.html",
        history=history,
        policy=policy,
        team_waiting=team_waiting,
        form=form or {"occurred_at": now, "category": "meals"},
        idempotency_key=str(uuid.uuid4()),
        **context,
    )


# Team (managers)


def team_page(
    request: Request,
    conn: Conn,
    error: str | None = None,
    notice: str | None = None,
) -> HTMLResponse | RedirectResponse:
    actor = _actor(request, conn)
    if actor is None:
        return RedirectResponse(DEMO, status_code=303)
    if Role.MANAGER not in actor.roles:
        denied = "Team approvals are for managers."
        return _render(
            request, conn, actor, "team.html", status_code=403, denied=denied
        )
    team = [
        e for e in employees.list_employees(conn, actor) if e.manager_id == actor.id
    ]
    return _render(
        request,
        conn,
        actor,
        "team.html",
        team=team,
        pending=_team_pending(conn, actor),
        error=error,
        notice=notice,
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
    actor = _actor(request, conn)
    if actor is None or not authz.is_finance(actor):
        message = CHOOSE_USER if actor is None else "The finance view is for finance."
        return _render(
            request,
            conn,
            actor,
            "finance.html",
            status_code=403,
            denied=message,
            error=error,
        )
    summaries = policies.list_policies(conn, actor)
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
            detail = policies.get_version_detail(conn, actor, summary.id, number)
        except NotFoundError as exc:
            error = exc.message
    labels = {}
    if detail is not None:
        labels.update({rule.clause: f"R{rule.id}" for rule in detail.rules})
        labels.update({item.clause: f"U{item.id}" for item in detail.uncompilable})
    return _render(
        request,
        conn,
        actor,
        "finance.html",
        policies=summaries,
        summary=summary,
        detail=detail,
        policy_html=highlight_clauses(detail.text, labels) if detail else "",
        editable=detail is not None and detail.status in ("draft", "compile_failed"),
        pending=expenses.list_expenses(conn, actor, status=ExpenseStatus.PENDING),
        error=error,
        notice=notice,
    )


def _try(request: Request, conn: Conn, action, notice: str) -> dict[str, str]:
    """Run `action(actor)`; return the notice, or the error to show instead."""
    actor = _actor(request, conn)
    if actor is None:
        return {"error": CHOOSE_USER}
    try:
        action(actor)
    except (CoveredError, ValidationError) as exc:
        return {"error": _message(exc)}
    return {"notice": notice}


def _attempt(
    request: Request, conn: Conn, policy_id: int, version: int, action, notice: str
) -> RedirectResponse:
    """Run a finance action as the current user and redirect back to /finance."""
    return _back(policy_id, version, **_try(request, conn, action, notice))


def _back(policy_id: int, version: int, **message: str) -> RedirectResponse:
    query = urlencode({"policy_id": policy_id, "version": version, **message})
    return RedirectResponse(f"/finance?{query}", status_code=303)


def review_rule(
    request: Request,
    conn: Conn,
    rule_id: int,
    status: Annotated[RuleStatus, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        request,
        conn,
        policy_id,
        version,
        lambda actor: policies.update_rule(conn, actor, rule_id, status=status),
        f"Rule R{rule_id} {status}.",
    )


def classify(
    request: Request,
    conn: Conn,
    item_id: int,
    effect: Annotated[UncompilableEffect, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
    categories: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    return _attempt(
        request,
        conn,
        policy_id,
        version,
        lambda actor: policies.classify_uncompilable(
            conn, actor, item_id, categories=categories or ["*"], effect=effect
        ),
        f"Clause U{item_id} confirmed.",
    )


def compile_draft(
    request: Request,
    conn: Conn,
    compiler: InjectedCompiler,
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        request,
        conn,
        policy_id,
        version,
        lambda actor: compile_version(conn, actor, policy_id, version, compiler),
        "Compiled: review the proposed rules.",
    )


def activate(
    request: Request,
    conn: Conn,
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        request,
        conn,
        policy_id,
        version,
        lambda actor: policies.activate_version(conn, actor, policy_id, version),
        f"Version {version} is now active.",
    )


def new_version(
    request: Request,
    conn: Conn,
    policy_id: Annotated[int, Form()],
    text: Annotated[str, Form()],
) -> RedirectResponse:
    actor = _actor(request, conn)
    if actor is None:
        return _back(policy_id, 0, error=CHOOSE_USER)
    try:
        created = policies.create_version(conn, actor, policy_id, text)
    except (CoveredError, ValidationError) as exc:
        return _back(policy_id, 0, error=_message(exc))
    return _back(policy_id, created.version, notice="Draft created: compile it next.")


def resolve(
    request: Request,
    conn: Conn,
    expense_id: int,
    resolution: Annotated[ExpenseStatus, Form()],
    policy_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
) -> RedirectResponse:
    return _attempt(
        request,
        conn,
        policy_id,
        version,
        lambda actor: expenses.resolve_expense(conn, actor, expense_id, resolution),
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
    ("/demo", "GET", demo_panel),
    ("/act-as", "POST", act_as),
    ("/employee", "GET", employee_page),
    ("/employee", "POST", employee_post),
    ("/employee/expenses/{expense_id}/resolve", "POST", employee_resolve),
    ("/team", "GET", team_page),
    ("/finance", "GET", finance_page),
    ("/finance/rules/{rule_id}", "POST", review_rule),
    ("/finance/uncompilable/{item_id}", "POST", classify),
    ("/finance/compile", "POST", compile_draft),
    ("/finance/activate", "POST", activate),
    ("/finance/versions", "POST", new_version),
    ("/finance/expenses/{expense_id}/resolve", "POST", resolve),
]

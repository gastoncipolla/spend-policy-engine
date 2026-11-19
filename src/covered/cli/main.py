"""`covered`: serve, seed, check, submit, policy ..., expenses ... (SPEC §8)."""

import uuid
from typing import Annotated

import typer

from covered.cli import expenses as expenses_cli
from covered.cli import policy as policy_cli
from covered.cli.context import database
from covered.cli.inputs import build_expense
from covered.cli.render import print_decision
from covered.domain import Decision
from covered.services import expenses
from covered.services.events import configure_logging
from covered.services.seed import reset_database
from covered.services.seed import seed as seed_demo
from covered.store.db import resolve_db_path

app = typer.Typer(help="Covered: will this expense be covered?", no_args_is_help=True)
app.add_typer(policy_cli.app, name="policy")
app.add_typer(expenses_cli.app, name="expenses")

Employee = Annotated[str, typer.Option(help="Employee id, e.g. ana.")]
Amount = Annotated[str, typer.Option(help="Decimal amount in USD, e.g. 80.00.")]
CategoryOpt = Annotated[str, typer.Option(help="Category code, e.g. meals.")]
At = Annotated[
    str | None,
    typer.Option(
        help="When it happened (ISO); no offset = company time. Default: now."
    ),
]
Merchant = Annotated[str | None, typer.Option()]
Justification = Annotated[str | None, typer.Option()]
PreApproval = Annotated[str | None, typer.Option(help="Pre-approval id.")]


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
) -> None:
    """Run the API and the pages with uvicorn."""
    import uvicorn

    from covered.api import create_app

    configure_logging()
    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def seed() -> None:
    """Reset the database and load the demo policies and employees (mock provider)."""
    db_path = resolve_db_path()
    conn = reset_database(db_path)
    try:
        for detail in seed_demo(conn):
            typer.echo(
                f"policy {detail.policy_id} v{detail.version}: "
                f"{len(detail.rules)} rules, {len(detail.uncompilable)} uncompilable, "
                f"status {detail.status}"
            )
    finally:
        conn.close()
    typer.secho(
        f"Seeded {db_path}: ana, bruno (Sales); carla, diego (Engineering).", fg="green"
    )


@app.command()
def check(
    employee: Employee,
    amount: Amount,
    category: CategoryOpt,
    at: At = None,
    merchant: Merchant = None,
    justification: Justification = None,
    pre_approval: PreApproval = None,
) -> None:
    """Will this expense be covered? Stores nothing."""
    expense = build_expense(**locals())
    with database() as conn:
        print_decision(expenses.check_expense(conn, expense))


@app.command()
def submit(
    employee: Employee,
    amount: Amount,
    category: CategoryOpt,
    at: At = None,
    merchant: Merchant = None,
    justification: Justification = None,
    pre_approval: PreApproval = None,
    key: Annotated[
        str | None, typer.Option(help="Idempotency key. Default: a new random one.")
    ] = None,
) -> None:
    """Submit an expense: evaluated and stored, consuming limits."""
    idempotency_key = key or str(uuid.uuid4())
    expense = build_expense(
        employee=employee,
        amount=amount,
        category=category,
        at=at,
        merchant=merchant,
        justification=justification,
        pre_approval=pre_approval,
    )
    with database() as conn:
        result = expenses.submit_expense(conn, expense, idempotency_key)
        decision = Decision.model_validate(result.body["decision"])
        replay = " (replayed)" if result.replayed else ""
        typer.echo(
            f"expense #{result.body['expense']['id']}{replay}, key {idempotency_key}"
        )
        print_decision(decision)

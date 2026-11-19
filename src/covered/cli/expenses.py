"""`covered expenses list|resolve`."""

from typing import Annotated

import typer

from covered.cli.context import AsUser, database
from covered.cli.render import print_expense
from covered.services import employees, expenses
from covered.services.seed import DEMO_FINANCE
from covered.store.records import ExpenseStatus

app = typer.Typer(help="List and resolve stored expenses.", no_args_is_help=True)


@app.command("list")
def list_(
    employee: Annotated[str | None, typer.Option(help="Employee id.")] = None,
    status: Annotated[ExpenseStatus | None, typer.Option(help="Filter.")] = None,
    as_user: AsUser = DEMO_FINANCE,
) -> None:
    """Stored expenses the user may see, newest first."""
    with database() as conn:
        actor = employees.act_as(conn, as_user)
        items = expenses.list_expenses(conn, actor, employee_id=employee, status=status)
        if not items:
            typer.echo("No expenses.")
        for item in items:
            print_expense(item)


@app.command()
def resolve(
    expense_id: Annotated[int, typer.Argument(help="Expense id.")],
    resolution: Annotated[str, typer.Argument(help="approved or rejected.")],
    as_user: AsUser = DEMO_FINANCE,
) -> None:
    """Approve or reject a pending expense (never your own)."""
    if resolution not in ("approved", "rejected"):
        raise typer.BadParameter("must be 'approved' or 'rejected'")
    with database() as conn:
        actor = employees.act_as(conn, as_user)
        item = expenses.resolve_expense(
            conn, actor, expense_id, ExpenseStatus(resolution)
        )
        print_expense(item)

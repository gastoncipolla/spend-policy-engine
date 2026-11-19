"""`covered expenses list|resolve`."""

from typing import Annotated

import typer

from covered.cli.context import database
from covered.cli.render import print_expense
from covered.services import expenses
from covered.store.records import ExpenseStatus

app = typer.Typer(help="List and resolve stored expenses.", no_args_is_help=True)


@app.command("list")
def list_(
    employee: Annotated[str | None, typer.Option(help="Employee id.")] = None,
    status: Annotated[ExpenseStatus | None, typer.Option(help="Filter.")] = None,
) -> None:
    """Stored expenses, newest first."""
    with database() as conn:
        items = expenses.list_expenses(conn, employee_id=employee, status=status)
        if not items:
            typer.echo("No expenses.")
        for item in items:
            print_expense(item)


@app.command()
def resolve(
    expense_id: Annotated[int, typer.Argument(help="Expense id.")],
    resolution: Annotated[str, typer.Argument(help="approved or rejected.")],
) -> None:
    """Approve or reject a pending expense."""
    if resolution not in ("approved", "rejected"):
        raise typer.BadParameter("must be 'approved' or 'rejected'")
    with database() as conn:
        item = expenses.resolve_expense(conn, expense_id, ExpenseStatus(resolution))
        print_expense(item)

"""`covered policy show|compile|activate`."""

import sqlite3
from typing import Annotated

import typer

from covered.cli.context import AsUser, database, fail
from covered.cli.render import print_version
from covered.domain.errors import NotFoundError
from covered.services import employees, policies
from covered.services.authz import Actor
from covered.services.compilation import compile_version
from covered.services.policies import PolicySummary
from covered.services.provider_compiler import default_compiler
from covered.services.seed import DEMO_FINANCE

app = typer.Typer(
    help="Show, compile and activate policy versions.", no_args_is_help=True
)

PolicyArg = Annotated[str, typer.Argument(help="Policy id or name, e.g. Sales.")]
VersionOpt = Annotated[
    int | None, typer.Option("--version", "-v", help="Default: the latest version.")
]


@app.command()
def show(
    policy: Annotated[str | None, typer.Argument(help="Policy id or name.")] = None,
    version: VersionOpt = None,
    as_user: AsUser = DEMO_FINANCE,
) -> None:
    """List policies, or show one version with its rules and clauses."""
    with database() as conn:
        actor = employees.act_as(conn, as_user)
        if policy is None:
            for summary in policies.list_policies(conn, actor):
                active = summary.active_version or "-"
                typer.echo(f"{summary.id}  {summary.name:<14} active version: {active}")
            return
        summary = find_policy(conn, actor, policy)
        number = version or _latest(summary)
        detail = policies.get_version_detail(conn, actor, summary.id, number)
        print_version(detail, summary.name)


@app.command("compile")
def compile_(
    policy: PolicyArg, version: VersionOpt = None, as_user: AsUser = DEMO_FINANCE
) -> None:
    """Compile a draft version with the active provider (mock or Anthropic)."""
    with database() as conn:
        actor = employees.act_as(conn, as_user)
        summary = find_policy(conn, actor, policy)
        compiler = default_compiler()
        typer.echo(f"provider: {compiler.provider_name}")
        detail = compile_version(
            conn, actor, summary.id, version or _latest(summary), compiler
        )
        print_version(detail, summary.name)
        if detail.compile_error:
            raise typer.Exit(code=1)


@app.command()
def activate(
    policy: PolicyArg, version: VersionOpt = None, as_user: AsUser = DEMO_FINANCE
) -> None:
    """Activate a fully reviewed version (the previous active one is retired)."""
    with database() as conn:
        actor = employees.act_as(conn, as_user)
        summary = find_policy(conn, actor, policy)
        detail = policies.activate_version(
            conn, actor, summary.id, version or _latest(summary)
        )
        typer.secho(f"{summary.name} version {detail.version} is active.", fg="green")


def find_policy(conn: sqlite3.Connection, actor: Actor, ref: str) -> PolicySummary:
    """A policy the actor may read, by id or name."""
    for summary in policies.list_policies(conn, actor):
        if ref == str(summary.id) or ref.casefold() == summary.name.casefold():
            return summary
    raise NotFoundError(f"policy {ref!r} not found")


def _latest(summary: PolicySummary) -> int:
    if not summary.versions:
        fail(f"policy {summary.name!r} has no versions")
    return max(ref.version for ref in summary.versions)

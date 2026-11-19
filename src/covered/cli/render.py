"""Terminal rendering of decisions, policies and expenses."""

import typer

from covered.domain import Decision, Outcome
from covered.domain.money import format_money
from covered.services.config import COMPANY_TZ
from covered.services.describe import (
    OUTCOME_LABELS,
    categories_text,
    describe_rule,
)
from covered.services.expenses import ExpenseWithDecision
from covered.services.policies import VersionDetail

OUTCOME_COLORS = {
    Outcome.APPROVED: typer.colors.GREEN,
    Outcome.NEEDS_APPROVAL: typer.colors.YELLOW,
    Outcome.REJECTED: typer.colors.RED,
}


def outcome_badge(outcome: Outcome) -> str:
    label = f" {OUTCOME_LABELS[outcome].upper()} "
    return typer.style(label, fg=typer.colors.BLACK, bg=OUTCOME_COLORS[outcome])


def print_decision(decision: Decision) -> None:
    typer.echo(f"{outcome_badge(decision.outcome)}  ", nl=False)
    typer.echo(f"policy {decision.policy_id} v{decision.policy_version}")
    for reason in decision.reasons:
        color = OUTCOME_COLORS[reason.outcome]
        marker = typer.style(
            "x" if reason.outcome is Outcome.REJECTED else "?", fg=color
        )
        source = f"rule {reason.rule_id}" if reason.rule_id else reason.source.value
        typer.echo(f"  {marker} {reason.message}  [{source}]")
        if reason.clause:
            typer.secho(f'      "{reason.clause}"', dim=True)
    for warning in decision.warnings:
        typer.echo(f"  {typer.style('!', fg=typer.colors.BLUE)} {warning.message}")
        typer.secho(f'      "{warning.clause}"', dim=True)


def print_expense(item: ExpenseWithDecision) -> None:
    expense = item.expense
    when = expense.occurred_at.astimezone(COMPANY_TZ).strftime("%Y-%m-%d %H:%M")
    merchant = f"  {expense.merchant}" if expense.merchant else ""
    typer.echo(
        f"#{expense.id:<4} {expense.employee_id:<8} {when}  "
        f"{format_money(expense.amount_minor):>12}  {expense.category}{merchant}  "
        f"[{expense.status}]"
    )


def print_version(detail: VersionDetail, policy_name: str) -> None:
    typer.secho(
        f"{policy_name} — version {detail.version} ({detail.status})", bold=True
    )
    if detail.compile_error:
        typer.secho(f"compile error: {detail.compile_error}", fg=typer.colors.RED)
    typer.echo("\nRules:")
    for rule in detail.rules:
        flags = f" flags={','.join(rule.flags)}" if rule.flags else ""
        typer.echo(
            f"  [{rule.id}] {describe_rule(rule.params)}  ({rule.status}, {rule.origin}{flags})"
        )
        typer.secho(f'      "{rule.clause}"', dim=True)
    typer.echo("\nUncompilable clauses:")
    for item in detail.uncompilable:
        typer.echo(
            f"  [{item.id}] {item.effect} on {categories_text(item.categories)}"
            f"  ({item.status}; {item.reason})"
        )
        typer.secho(f'      "{item.clause}"', dim=True)
    uncovered = ", ".join(detail.uncovered_categories) or "none"
    typer.echo(f"\nUncovered categories (always need approval): {uncovered}")

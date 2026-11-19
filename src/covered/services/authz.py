"""Authorization (SPEC §12a): who may do what, in one place.

Deny by default: every function below allows only what the permission matrix
explicitly grants. Services call these before touching data, so the API, the
pages and the CLI all get the same answers.

- `require_*` raise `ForbiddenError` (403) for role or separation-of-duties
  violations.
- Hidden resources are reported as `NotFoundError` (404) by the services, using
  `can_see_employee`, so their existence is never revealed.
"""

from covered.domain.errors import ForbiddenError
from covered.store.records import Employee, Role

Actor = Employee
"""The authenticated user performing the action."""


def is_finance(actor: Actor) -> bool:
    return Role.FINANCE in actor.roles


def manages(actor: Actor, employee: Employee) -> bool:
    """`employee` is on `actor`'s team: actor is a manager and their direct manager."""
    return Role.MANAGER in actor.roles and employee.manager_id == actor.id


def can_see_employee(actor: Actor, employee: Employee) -> bool:
    """Self, own team (managers), everyone (finance). Also governs their expenses."""
    return actor.id == employee.id or manages(actor, employee) or is_finance(actor)


def require_own_expense(actor: Actor, employee_id: str) -> None:
    """Check/submit: everyone, finance included, only for themselves."""
    if employee_id != actor.id:
        raise ForbiddenError("you can only check or submit your own expenses")


def require_can_resolve(actor: Actor, owner: Employee) -> None:
    """Resolve: never your own; managers their team's; finance anyone's."""
    if owner.id == actor.id:
        raise ForbiddenError(
            "separation of duties: nobody resolves their own expense, finance "
            "included; your manager or finance must resolve it"
        )
    if not (manages(actor, owner) or is_finance(actor)):
        raise ForbiddenError("only the employee's manager or finance can resolve it")


def can_read_policy(actor: Actor, policy_id: int) -> bool:
    """Finance reads every policy; everyone else only the one they are on."""
    return is_finance(actor) or actor.policy_id == policy_id


def require_finance(actor: Actor, action: str) -> None:
    """Policy administration: create, compile, review, classify, activate."""
    if not is_finance(actor):
        raise ForbiddenError(f"only finance can {action}")

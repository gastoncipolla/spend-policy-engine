"""Demo data (SPEC §9, §12a): two policies compiled from the sample texts and
five demo users with roles, managers and fixed demo tokens.

Seeding goes through the normal path (create version -> compile -> review ->
activate) acting as the finance user, so the demo exercises the same code and
the same authorization a real policy would.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from covered.compiler import MockProvider
from covered.domain.errors import CoveredError
from covered.services import employees, policies
from covered.services.authz import Actor
from covered.services.compilation import Compiler, compile_version
from covered.services.policies import VersionDetail
from covered.services.provider_compiler import ProviderCompiler
from covered.store.db import open_database
from covered.store.records import Role, RuleStatus, VersionStatus

SAMPLE_POLICIES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "policies"
"""`<repo>/fixtures/policies` (this file is `<repo>/src/covered/services/`)."""


@dataclass(frozen=True)
class SamplePolicy:
    name: str
    file: str
    members: tuple[str, ...]  # user ids on this policy


SAMPLE_POLICIES = (
    SamplePolicy("Sales", "sales.md", ("ana", "bruno")),
    SamplePolicy("Engineering", "engineering.md", ("carla", "diego", "fede", "gabi")),
)


@dataclass(frozen=True)
class DemoUser:
    id: str
    name: str
    roles: tuple[Role, ...]
    manager_id: str | None

    @property
    def token(self) -> str:
        """Demo-only bearer token. Never use fixed tokens outside a demo."""
        return f"demo-{self.id}"


E, M, F = Role.EMPLOYEE, Role.MANAGER, Role.FINANCE
DEMO_USERS = (  # managers before their reports (manager_id is a foreign key)
    DemoUser("fede", "Fede", (E, F), None),
    # A second finance user, so each finance user's own pending expenses can be
    # resolved by someone else (separation of duties).
    DemoUser("gabi", "Gabi", (E, F), None),
    DemoUser("bruno", "Bruno", (E, M), "fede"),
    DemoUser("diego", "Diego", (E, M), "fede"),
    DemoUser("ana", "Ana", (E,), "bruno"),
    DemoUser("carla", "Carla", (E,), "diego"),
)
DEMO_FINANCE = "fede"


class SeedError(CoveredError):
    code = "seed_failed"


def reset_database(db_path: str) -> sqlite3.Connection:
    """Delete the SQLite file (and its WAL/SHM side files) and recreate the schema."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    return open_database(db_path)


def seed(
    conn: sqlite3.Connection,
    compiler: Compiler | None = None,
    policies_dir: Path = SAMPLE_POLICIES_DIR,
) -> list[VersionDetail]:
    """Create, compile, approve and activate both sample policies on an empty DB.

    Uses the mock provider by default: the demo never needs an API key.
    """
    compiler = compiler or ProviderCompiler(MockProvider())
    for user in DEMO_USERS:
        employees.create_employee(
            conn,
            user.id,
            user.name,
            None,
            roles=user.roles,
            manager_id=user.manager_id,
            token=user.token,
        )
    finance = employees.act_as(conn, DEMO_FINANCE)
    activated = []
    for sample in SAMPLE_POLICIES:
        text = (policies_dir / sample.file).read_text(encoding="utf-8")
        detail = _compile_and_activate(conn, finance, sample.name, text, compiler)
        for user_id in sample.members:
            employees.assign_policy(conn, user_id, detail.policy_id)
        activated.append(detail)
    return activated


def _compile_and_activate(
    conn: sqlite3.Connection, finance: Actor, name: str, text: str, compiler: Compiler
) -> VersionDetail:
    policy = policies.create_policy(conn, finance, name)
    version = policies.create_version(conn, finance, policy.id, text).version
    detail = compile_version(conn, finance, policy.id, version, compiler)
    if detail.status is VersionStatus.COMPILE_FAILED:
        raise SeedError(f"compiling {name!r} failed: {detail.compile_error}")
    # Finance (fede) approves every proposed rule and confirm every
    # uncompilable clause with the classification the compiler proposed.
    for rule in detail.rules:
        if rule.status is RuleStatus.PROPOSED:
            policies.update_rule(conn, finance, rule.id, status=RuleStatus.APPROVED)
    for item in detail.uncompilable:
        policies.classify_uncompilable(
            conn, finance, item.id, categories=list(item.categories), effect=item.effect
        )
    return policies.activate_version(conn, finance, policy.id, version)

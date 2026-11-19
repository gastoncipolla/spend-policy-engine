"""Demo data (SPEC §9): two policies compiled from the sample texts, four employees.

Seeding goes through the normal path (create version -> compile -> review ->
activate), so the demo exercises the same code a real policy would.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from covered.compiler import MockProvider
from covered.domain.errors import CoveredError
from covered.services import employees, policies
from covered.services.compilation import Compiler, compile_version
from covered.services.policies import VersionDetail
from covered.services.provider_compiler import ProviderCompiler
from covered.store.db import open_database
from covered.store.records import RuleStatus, VersionStatus

SAMPLE_POLICIES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "policies"
"""`<repo>/fixtures/policies` (this file is `<repo>/src/covered/services/`)."""


@dataclass(frozen=True)
class SamplePolicy:
    name: str
    file: str
    employees: tuple[tuple[str, str], ...]  # (id, name)


SAMPLE_POLICIES = (
    SamplePolicy("Sales", "sales.md", (("ana", "Ana"), ("bruno", "Bruno"))),
    SamplePolicy(
        "Engineering", "engineering.md", (("carla", "Carla"), ("diego", "Diego"))
    ),
)


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
    activated = []
    for sample in SAMPLE_POLICIES:
        text = (policies_dir / sample.file).read_text(encoding="utf-8")
        detail = _compile_and_activate(conn, sample.name, text, compiler)
        for employee_id, name in sample.employees:
            employees.create_employee(conn, employee_id, name, detail.policy_id)
        activated.append(detail)
    return activated


def _compile_and_activate(
    conn: sqlite3.Connection, name: str, text: str, compiler: Compiler
) -> VersionDetail:
    policy = policies.create_policy(conn, name)
    version = policies.create_version(conn, policy.id, text).version
    detail = compile_version(conn, policy.id, version, compiler)
    if detail.status is VersionStatus.COMPILE_FAILED:
        raise SeedError(f"compiling {name!r} failed: {detail.compile_error}")
    # The demo plays finance: approve every proposed rule and confirm every
    # uncompilable clause with the classification the compiler proposed.
    for rule in detail.rules:
        if rule.status is RuleStatus.PROPOSED:
            policies.update_rule(conn, rule.id, status=RuleStatus.APPROVED)
    for item in detail.uncompilable:
        policies.classify_uncompilable(
            conn, item.id, categories=list(item.categories), effect=item.effect
        )
    return policies.activate_version(conn, policy.id, version)

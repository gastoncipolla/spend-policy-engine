"""Policy endpoints: versions, compile, finance review, activation (SPEC §5, §7)."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from covered.api.deps import Conn, InjectedCompiler
from covered.domain import RuleParams, UncompilableEffect
from covered.services import policies
from covered.services.compilation import compile_version
from covered.services.policies import PolicySummary, VersionDetail
from covered.store.records import (
    Policy,
    PolicyVersion,
    RuleStatus,
    StoredRule,
    StoredUncompilable,
)

router = APIRouter(tags=["policies"])

NonEmpty = Annotated[str, Field(min_length=1)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreatePolicyBody(_Body):
    name: NonEmpty


class CreateVersionBody(_Body):
    text: NonEmpty


class ManualRuleBody(_Body):
    params: RuleParams
    clause: NonEmpty


class PatchRuleBody(_Body):
    status: RuleStatus | None = None
    params: RuleParams | None = None


class PatchUncompilableBody(_Body):
    categories: list[str]
    effect: UncompilableEffect


@router.get("/policies")
def list_policies(conn: Conn) -> list[PolicySummary]:
    return policies.list_policies(conn)


@router.post("/policies", status_code=201)
def create_policy(body: CreatePolicyBody, conn: Conn) -> Policy:
    return policies.create_policy(conn, body.name)


@router.post("/policies/{policy_id}/versions", status_code=201)
def create_version(
    policy_id: int, body: CreateVersionBody, conn: Conn
) -> PolicyVersion:
    return policies.create_version(conn, policy_id, body.text)


@router.get("/policies/{policy_id}/versions/{version}")
def get_version(policy_id: int, version: int, conn: Conn) -> VersionDetail:
    return policies.get_version_detail(conn, policy_id, version)


@router.post("/policies/{policy_id}/versions/{version}/compile")
def compile_policy_version(
    policy_id: int, version: int, conn: Conn, compiler: InjectedCompiler
) -> VersionDetail:
    """A compile failure is reported in the body (`status: compile_failed`), not as an HTTP error."""
    return compile_version(conn, policy_id, version, compiler)


@router.post("/policies/{policy_id}/versions/{version}/rules", status_code=201)
def add_manual_rule(
    policy_id: int, version: int, body: ManualRuleBody, conn: Conn
) -> StoredRule:
    return policies.add_manual_rule(conn, policy_id, version, body.params, body.clause)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: PatchRuleBody, conn: Conn) -> StoredRule:
    return policies.update_rule(conn, rule_id, status=body.status, params=body.params)


@router.patch("/uncompilable/{item_id}")
def classify_uncompilable(
    item_id: int, body: PatchUncompilableBody, conn: Conn
) -> StoredUncompilable:
    return policies.classify_uncompilable(
        conn, item_id, categories=body.categories, effect=body.effect
    )


@router.post("/policies/{policy_id}/versions/{version}/activate")
def activate_version(policy_id: int, version: int, conn: Conn) -> VersionDetail:
    return policies.activate_version(conn, policy_id, version)

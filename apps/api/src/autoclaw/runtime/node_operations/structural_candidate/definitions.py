from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts import PolicyDefinitionInput, RoleDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.structural_candidate.models import (
    StructuralRevisionCandidate,
)


@dataclass(frozen=True)
class ResolvedDefinition:
    id: str
    revision_no: int
    definition: RoleDefinitionInput | PolicyDefinitionInput


async def resolve_current_node_definitions(
    session: AsyncSession,
    *,
    role_key: str,
    policy_key: str,
    node_kind: NodeKind,
) -> tuple[ResolvedDefinition, ResolvedDefinition]:
    role_row = await session.get(RoleDefinitionModel, role_key)
    if role_row is None or role_row.current_revision_no is None:
        raise _failure(OperationFailureCode.MISSING_RESOURCE, f"unknown role '{role_key}'")
    role_revision = await session.scalar(
        select(RoleRevisionModel).where(
            RoleRevisionModel.role_key == role_key,
            RoleRevisionModel.revision_no == role_row.current_revision_no,
        )
    )
    if role_revision is None:
        raise _failure(OperationFailureCode.MISSING_RESOURCE, f"unknown role '{role_key}'")
    role_definition = _parse_role(role_key, role_revision.content_json)
    _require_role_kind(role_key, role_definition, node_kind)
    role = ResolvedDefinition(role_key, role_revision.revision_no, role_definition)
    policy_row = await session.get(PolicyDefinitionModel, policy_key)
    if policy_row is None or policy_row.current_revision_no is None:
        raise _failure(OperationFailureCode.MISSING_RESOURCE, f"unknown policy '{policy_key}'")
    policy_revision = await session.scalar(
        select(PolicyRevisionModel).where(
            PolicyRevisionModel.policy_key == policy_key,
            PolicyRevisionModel.revision_no == policy_row.current_revision_no,
        )
    )
    if policy_revision is None:
        raise _failure(OperationFailureCode.MISSING_RESOURCE, f"unknown policy '{policy_key}'")
    policy_definition = _parse_policy(policy_key, policy_revision.content_json)
    _require_policy_kind(policy_key, policy_definition, node_kind)
    return role, ResolvedDefinition(
        policy_key,
        policy_revision.revision_no,
        policy_definition,
    )


async def validate_candidate_definition_references(
    session: AsyncSession,
    candidate: StructuralRevisionCandidate,
) -> None:
    for node in candidate.nodes:
        role_revision = await session.scalar(
            select(RoleRevisionModel).where(
                RoleRevisionModel.role_key == node.role_key,
                RoleRevisionModel.revision_no == node.role_revision_no,
            )
        )
        if role_revision is None:
            raise _failure(
                OperationFailureCode.MISSING_RESOURCE,
                f"missing pinned role '{node.role_key}' revision {node.role_revision_no}",
            )
        role = _parse_role(node.role_key, role_revision.content_json)
        _require_role_kind(node.role_key, role, node.structural_kind)
        policy = await resolve_pinned_policy_definition(
            session,
            policy_key=node.policy_key,
            policy_revision_no=node.policy_revision_no,
        )
        _require_policy_kind(node.policy_key, policy, node.structural_kind)


async def resolve_pinned_policy_definition(
    session: AsyncSession,
    *,
    policy_key: str,
    policy_revision_no: int,
) -> PolicyDefinitionInput:
    policy_revision = await session.scalar(
        select(PolicyRevisionModel).where(
            PolicyRevisionModel.policy_key == policy_key,
            PolicyRevisionModel.revision_no == policy_revision_no,
        )
    )
    if policy_revision is None:
        raise _failure(
            OperationFailureCode.MISSING_RESOURCE,
            f"missing pinned policy '{policy_key}' revision {policy_revision_no}",
        )
    return _parse_policy(policy_key, policy_revision.content_json)


def _parse_role(role_key: str, value: dict[str, object]) -> RoleDefinitionInput:
    try:
        role = RoleDefinitionInput.model_validate(value)
    except ValidationError as exc:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            f"role '{role_key}' has invalid controller-owned content",
        ) from exc
    if role.id != role_key:
        raise _failure(OperationFailureCode.ILLEGAL_STATE, f"role '{role_key}' id mismatch")
    return role


def _parse_policy(policy_key: str, value: dict[str, object]) -> PolicyDefinitionInput:
    try:
        policy = PolicyDefinitionInput.model_validate(value)
    except ValidationError as exc:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            f"policy '{policy_key}' has invalid controller-owned content",
        ) from exc
    if policy.id != policy_key:
        raise _failure(OperationFailureCode.ILLEGAL_STATE, f"policy '{policy_key}' id mismatch")
    return policy


def _require_role_kind(
    role_key: str,
    role: RoleDefinitionInput,
    node_kind: NodeKind,
) -> None:
    if node_kind not in role.allowed_node_kinds:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            f"role '{role_key}' does not allow {node_kind.value} nodes",
        )


def _require_policy_kind(
    policy_key: str,
    policy: PolicyDefinitionInput,
    node_kind: NodeKind,
) -> None:
    if node_kind not in policy.applies_to:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            f"policy '{policy_key}' does not apply to {node_kind.value} nodes",
        )


def _failure(code: OperationFailureCode, summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(code=code, summary=summary, is_retryable=False)


__all__ = [
    "ResolvedDefinition",
    "resolve_current_node_definitions",
    "resolve_pinned_policy_definition",
    "validate_candidate_definition_references",
]

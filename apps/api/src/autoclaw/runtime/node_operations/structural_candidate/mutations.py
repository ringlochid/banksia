from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.compiler.normalize import (
    normalize_child_defaults,
    normalize_consume_buckets,
    normalize_produces,
)
from autoclaw.definitions.contracts.workflow import CriteriaDeclaration, NodeKind
from autoclaw.persistence.models import AssignmentModel, AttemptModel
from autoclaw.runtime.contracts import ChildNodeDraft
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.contracts import (
    AddChildRequest,
    NodeOperationName,
    RemoveChildRequest,
    UpdateChildRequest,
)
from autoclaw.runtime.node_operations.structural_candidate.definitions import (
    resolve_current_node_definitions,
)
from autoclaw.runtime.node_operations.structural_candidate.models import (
    StructuralCriteria,
    StructuralNodeCandidate,
    StructuralRevisionCandidate,
    relational_subtree,
)


async def mutate_structural_candidate(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    nodes: dict[str, StructuralNodeCandidate],
    open_work: set[str],
    operation_name: NodeOperationName,
    request: BaseModel,
) -> tuple[str, str]:
    owned = relational_subtree(nodes, authority.node_key)
    if authority.node_key not in owned:
        raise _failure(OperationFailureCode.ILLEGAL_STATE, "current node is missing")
    if operation_name == NodeOperationName.ADD_CHILD:
        assert isinstance(request, AddChildRequest)
        await _apply_add(session, authority, nodes, owned, request)
        return request.payload.child.node_key, "add_child"
    if operation_name == NodeOperationName.UPDATE_CHILD:
        assert isinstance(request, UpdateChildRequest)
        await _apply_update(session, authority, nodes, owned, open_work, request)
        return request.payload.child_node_key, "update_child"
    assert operation_name == NodeOperationName.REMOVE_CHILD
    assert isinstance(request, RemoveChildRequest)
    _apply_remove(authority, nodes, owned, open_work, request)
    return request.payload.child_node_key, "remove_child"


async def read_open_work_node_keys(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> set[str]:
    return set(
        await session.scalars(
            select(AssignmentModel.node_key)
            .join(
                AttemptModel,
                AttemptModel.attempt_id == AssignmentModel.current_attempt_id,
            )
            .where(
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.flow_id == authority.flow_id,
                AttemptModel.status.in_(("pending", "running")),
            )
        )
    )


def validate_open_work_preserved(
    source: StructuralRevisionCandidate,
    candidate: StructuralRevisionCandidate,
    open_work: set[str],
) -> None:
    source_nodes = source.nodes_by_key
    candidate_nodes = candidate.nodes_by_key
    for node_key in sorted(open_work):
        before = source_nodes.get(node_key)
        after = candidate_nodes.get(node_key)
        if before is None:
            continue
        if after is None or _execution_contract(before) != _execution_contract(after):
            raise _failure(
                OperationFailureCode.ILLEGAL_STATE,
                f"structural change would invalidate open current work on '{node_key}'",
            )


async def _apply_add(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    nodes: dict[str, StructuralNodeCandidate],
    owned: set[str],
    request: AddChildRequest,
) -> None:
    draft = request.payload.child
    parent_key = draft.parent_node_key or authority.node_key
    parent = nodes.get(parent_key)
    if parent is None or parent_key not in owned:
        raise _failure(
            OperationFailureCode.ILLEGAL_TARGET_RELATION,
            "new children must remain inside the caller-owned subtree",
        )
    if parent.structural_kind == NodeKind.WORKER:
        raise _failure(
            OperationFailureCode.ILLEGAL_TARGET_RELATION,
            "worker nodes cannot own structural children",
        )
    await _add_draft_subtree(
        session,
        nodes,
        draft,
        parent_key=parent_key,
        next_order_index=max((node.order_index for node in nodes.values()), default=-1) + 1,
    )


async def _add_draft_subtree(
    session: AsyncSession,
    nodes: dict[str, StructuralNodeCandidate],
    draft: ChildNodeDraft,
    *,
    parent_key: str,
    next_order_index: int,
) -> int:
    if draft.node_key in nodes:
        raise _failure(
            OperationFailureCode.NAME_COLLISION,
            f"node key '{draft.node_key}' already exists",
        )
    node_kind = NodeKind.PARENT if draft.children else NodeKind.WORKER
    role, policy = await resolve_current_node_definitions(
        session,
        role_key=draft.role,
        policy_key=draft.policy,
        node_kind=node_kind,
    )
    nodes[draft.node_key] = StructuralNodeCandidate(
        node_key=draft.node_key,
        parent_node_key=parent_key,
        structural_kind=node_kind,
        role_key=role.id,
        role_revision_no=role.revision_no,
        role_description=role.definition.description,
        role_instruction=role.definition.instruction,
        policy_key=policy.id,
        policy_revision_no=policy.revision_no,
        policy_description=policy.definition.description,
        policy_instruction=policy.definition.instruction,
        provider=draft.provider,
        description=draft.description,
        node_instruction=draft.instruction,
        local_consumes=normalize_consume_buckets(draft.consumes),
        consumes=None,
        produces=normalize_produces(draft.produces),
        own_criteria=tuple(_draft_criterion(draft.node_key, item) for item in draft.criteria or ()),
        criteria=(),
        child_defaults=normalize_child_defaults(draft.child_defaults),
        child_node_keys=(),
        state="ready",
        current_assignment_id=None,
        order_index=next_order_index,
    )
    next_order_index += 1
    for child in draft.children or ():
        next_order_index = await _add_draft_subtree(
            session,
            nodes,
            child,
            parent_key=draft.node_key,
            next_order_index=next_order_index,
        )
    return next_order_index


async def _apply_update(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    nodes: dict[str, StructuralNodeCandidate],
    owned: set[str],
    open_work: set[str],
    request: UpdateChildRequest,
) -> None:
    target_key = request.payload.child_node_key
    if target_key == authority.node_key or target_key not in owned:
        raise _failure(
            OperationFailureCode.ILLEGAL_TARGET_RELATION,
            "update_child must target a descendant in the caller-owned subtree",
        )
    if target_key in open_work:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            "cannot change a node that has current open work",
        )
    target = nodes[target_key]
    patch = request.payload.patch
    if "role" in patch.model_fields_set or "policy" in patch.model_fields_set:
        role_key = patch.role if patch.role is not None else target.role_key
        policy_key = patch.policy if patch.policy is not None else target.policy_key
        role, policy = await resolve_current_node_definitions(
            session,
            role_key=role_key,
            policy_key=policy_key,
            node_kind=target.structural_kind,
        )
        target = replace(
            target,
            role_key=role.id,
            role_revision_no=role.revision_no,
            role_description=role.definition.description,
            role_instruction=role.definition.instruction,
            policy_key=policy.id,
            policy_revision_no=policy.revision_no,
            policy_description=policy.definition.description,
            policy_instruction=policy.definition.instruction,
        )
    nodes[target_key] = replace(
        target,
        provider=(patch.provider if "provider" in patch.model_fields_set else target.provider),
        description=(
            patch.description
            if "description" in patch.model_fields_set and patch.description is not None
            else target.description
        ),
        node_instruction=(
            patch.instruction
            if "instruction" in patch.model_fields_set
            else target.node_instruction
        ),
        local_consumes=(
            normalize_consume_buckets(patch.consumes)
            if "consumes" in patch.model_fields_set
            else target.local_consumes
        ),
        produces=(
            normalize_produces(patch.produces)
            if "produces" in patch.model_fields_set
            else target.produces
        ),
        own_criteria=(
            tuple(_draft_criterion(target_key, item) for item in patch.criteria or ())
            if "criteria" in patch.model_fields_set
            else target.own_criteria
        ),
        child_defaults=(
            normalize_child_defaults(patch.child_defaults)
            if "child_defaults" in patch.model_fields_set
            else target.child_defaults
        ),
    )


def _apply_remove(
    authority: NodeOperationAuthority,
    nodes: dict[str, StructuralNodeCandidate],
    owned: set[str],
    open_work: set[str],
    request: RemoveChildRequest,
) -> None:
    target_key = request.payload.child_node_key
    if target_key == authority.node_key or target_key not in owned:
        raise _failure(
            OperationFailureCode.ILLEGAL_TARGET_RELATION,
            "remove_child must target a descendant in the caller-owned subtree",
        )
    removal = relational_subtree(nodes, target_key)
    blocked = sorted(removal & open_work)
    if blocked:
        raise _failure(
            OperationFailureCode.ILLEGAL_STATE,
            "cannot remove a subtree that has current open work: " + ", ".join(blocked),
        )
    for node_key in removal:
        nodes.pop(node_key)


def _draft_criterion(
    node_key: str,
    criterion: CriteriaDeclaration,
) -> StructuralCriteria:
    return StructuralCriteria(
        owner_node_key=node_key,
        slot=criterion.slot,
        description=criterion.description,
        criteria=tuple(criterion.criteria),
    )


def _execution_contract(node: StructuralNodeCandidate) -> tuple[object, ...]:
    return (
        node.parent_node_key,
        node.structural_kind,
        node.role_key,
        node.role_revision_no,
        node.policy_key,
        node.policy_revision_no,
        node.provider,
        node.description,
        node.node_instruction,
        node.consumes,
        node.produces,
        node.criteria,
        node.child_defaults,
    )


def _failure(code: OperationFailureCode, summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(code=code, summary=summary, is_retryable=False)


__all__ = [
    "mutate_structural_candidate",
    "read_open_work_node_keys",
    "validate_open_work_preserved",
]

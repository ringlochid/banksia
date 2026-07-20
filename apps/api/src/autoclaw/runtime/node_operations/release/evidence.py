from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    ArtifactPublicationModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import (
    RuntimeOperationError,
    missing_required_publication_error,
)
from autoclaw.runtime.node_operations.release.basis import ReleaseBasis
from autoclaw.runtime.node_operations.release.publications import (
    read_required_current_publications,
    require_current_assignment_criteria,
)


async def release_green_is_ready(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> bool:
    try:
        await require_release_green_basis(session, authority)
    except RuntimeOperationError:
        return False
    return True


async def release_blocked_is_ready(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> bool:
    try:
        await require_release_blocked_basis(session, authority)
    except RuntimeOperationError:
        return False
    return True


async def require_release_green_basis(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> ReleaseBasis:
    nodes = await _ordered_subtree_nodes(session, authority)
    descendants = tuple(node for node in nodes if node.node_key != authority.node_key)
    assignments = await _current_assignments_by_node(session, authority, descendants)

    for child in descendants:
        if child.parent_node_key == authority.node_key and child.node_key not in assignments:
            raise _illegal_state(
                f"release_green requires current work for direct child '{child.node_key}'"
            )

    await require_current_assignment_criteria(session, authority.assignment)
    artifacts = list(await read_required_current_publications(session, authority.assignment))
    checkpoints: list[AttemptCheckpointModel] = []
    for node in descendants:
        assignment = assignments.get(node.node_key)
        if assignment is None:
            continue
        checkpoint = await _require_terminal_assignment(
            session,
            authority,
            assignment,
            required_outcome="green",
            action="release_green",
        )
        await require_current_assignment_criteria(session, assignment)
        checkpoints.append(checkpoint)
        artifacts.extend(await read_required_current_publications(session, assignment))

    return ReleaseBasis(
        checkpoints=_unique_checkpoints(checkpoints),
        artifacts=_unique_publications(artifacts),
    )


async def require_release_blocked_basis(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> ReleaseBasis:
    if authority.node_kind != NodeKind.ROOT:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_CALLER,
            summary="release_blocked is root-only",
            is_retryable=False,
        )
    await require_current_assignment_criteria(session, authority.assignment)
    root_checkpoint = await _latest_checkpoint(
        session,
        authority=authority,
        assignment=authority.assignment,
        attempt=authority.attempt,
        authoring_dispatch_id=authority.dispatch_id,
    )
    if (
        root_checkpoint is None
        or root_checkpoint.checkpoint_kind != "terminal"
        or root_checkpoint.outcome != "blocked"
    ):
        raise missing_required_publication_error(
            "release_blocked requires a current terminal-blocked root checkpoint"
        )

    nodes = await _ordered_subtree_nodes(session, authority)
    descendants = tuple(node for node in nodes if node.node_key != authority.node_key)
    assignments = await _current_assignments_by_node(session, authority, descendants)
    checkpoints = [root_checkpoint]
    for node in descendants:
        assignment = assignments.get(node.node_key)
        if assignment is None:
            continue
        checkpoint = await _require_terminal_assignment(
            session,
            authority,
            assignment,
            required_outcome=None,
            action="release_blocked",
        )
        await require_current_assignment_criteria(session, assignment)
        checkpoints.append(checkpoint)

    return ReleaseBasis(
        checkpoints=_unique_checkpoints(checkpoints),
        artifacts=(),
    )


async def _ordered_subtree_nodes(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> tuple[FlowNodeModel, ...]:
    rows = tuple(
        await session.scalars(
            select(FlowNodeModel)
            .where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
            )
            .order_by(FlowNodeModel.order_index, FlowNodeModel.node_key)
        )
    )
    nodes_by_key = {row.node_key: row for row in rows}
    children: dict[str, list[FlowNodeModel]] = {}
    for row in rows:
        if row.parent_node_key is not None:
            children.setdefault(row.parent_node_key, []).append(row)

    subtree: list[FlowNodeModel] = []
    pending = [authority.node_key]
    while pending:
        node_key = pending.pop(0)
        current_node = nodes_by_key.get(node_key)
        if current_node is None:
            raise _illegal_state(f"active structural node '{node_key}' is missing")
        subtree.append(current_node)
        pending.extend(child.node_key for child in children.get(node_key, ()))
    return tuple(subtree)


async def _current_assignments_by_node(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    nodes: tuple[FlowNodeModel, ...],
) -> dict[str, AssignmentModel]:
    assignment_ids = tuple(
        node.current_assignment_id for node in nodes if node.current_assignment_id is not None
    )
    if not assignment_ids:
        return {}
    rows = tuple(
        await session.scalars(
            select(AssignmentModel).where(
                AssignmentModel.assignment_id.in_(assignment_ids),
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.flow_id == authority.flow_id,
                AssignmentModel.flow_revision_id == authority.flow_revision_id,
            )
        )
    )
    assignments = {row.node_key: row for row in rows}
    for node in nodes:
        if node.current_assignment_id is None:
            continue
        assignment = assignments.get(node.node_key)
        if (
            assignment is None
            or assignment.assignment_id != node.current_assignment_id
            or assignment.flow_node_id != node.flow_node_id
        ):
            raise _illegal_state(
                f"node '{node.node_key}' has stale or cross-lineage assignment truth"
            )
    return assignments


async def _require_terminal_assignment(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    assignment: AssignmentModel,
    *,
    required_outcome: str | None,
    action: str,
) -> AttemptCheckpointModel:
    if assignment.current_attempt_id is None:
        raise _illegal_state(
            f"{action} requires a current attempt for assignment '{assignment.assignment_key}'"
        )
    attempt = await session.get(AttemptModel, assignment.current_attempt_id)
    if (
        attempt is None
        or attempt.task_id != authority.task_id
        or attempt.flow_id != authority.flow_id
        or attempt.assignment_id != assignment.assignment_id
        or attempt.status != "completed"
        or attempt.terminal_outcome not in {"green", "blocked"}
        or (required_outcome is not None and attempt.terminal_outcome != required_outcome)
    ):
        expected = required_outcome or "green-or-blocked"
        raise _illegal_state(
            f"{action} requires terminal-{expected} truth for "
            f"assignment '{assignment.assignment_key}'"
        )
    checkpoint = await _latest_checkpoint(
        session,
        authority=authority,
        assignment=assignment,
        attempt=attempt,
        authoring_dispatch_id=None,
    )
    if (
        checkpoint is None
        or checkpoint.checkpoint_kind != "terminal"
        or checkpoint.outcome != attempt.terminal_outcome
    ):
        raise missing_required_publication_error(
            f"{action} requires the terminal checkpoint for "
            f"assignment '{assignment.assignment_key}'"
        )
    return checkpoint


async def _latest_checkpoint(
    session: AsyncSession,
    *,
    authority: NodeOperationAuthority,
    assignment: AssignmentModel,
    attempt: AttemptModel,
    authoring_dispatch_id: str | None,
) -> AttemptCheckpointModel | None:
    statement = select(AttemptCheckpointModel).where(
        AttemptCheckpointModel.task_id == authority.task_id,
        AttemptCheckpointModel.flow_id == authority.flow_id,
        AttemptCheckpointModel.assignment_id == assignment.assignment_id,
        AttemptCheckpointModel.attempt_id == attempt.attempt_id,
    )
    if authoring_dispatch_id is not None:
        statement = statement.where(
            AttemptCheckpointModel.authoring_dispatch_id == authoring_dispatch_id
        )
    return cast(
        AttemptCheckpointModel | None,
        await session.scalar(
            statement.order_by(
                AttemptCheckpointModel.recorded_at.desc(),
                AttemptCheckpointModel.checkpoint_id.desc(),
            ).limit(1)
        ),
    )


def _unique_checkpoints(
    checkpoints: list[AttemptCheckpointModel],
) -> tuple[AttemptCheckpointModel, ...]:
    return tuple({row.checkpoint_id: row for row in checkpoints}.values())


def _unique_publications(
    publications: list[ArtifactPublicationModel],
) -> tuple[ArtifactPublicationModel, ...]:
    return tuple({row.artifact_publication_id: row for row in publications}.values())


def _illegal_state(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=summary,
        is_retryable=False,
    )


__all__ = [
    "release_blocked_is_ready",
    "release_green_is_ready",
    "require_release_blocked_basis",
    "require_release_green_basis",
]

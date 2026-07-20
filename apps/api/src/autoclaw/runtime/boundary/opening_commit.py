from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkspaceBindingModel,
)
from autoclaw.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from autoclaw.runtime.dispatch.preparation import PreparedDispatchRequest
from autoclaw.runtime.dispatch.prompt_snapshot import BoundaryPromptSnapshot


class BoundaryOpeningCommitSnapshot(Protocol):
    @property
    def source_committed_at(self) -> datetime: ...

    @property
    def flow_control_revision(self) -> int: ...

    @property
    def task_root_path(self) -> str: ...

    @property
    def workspace_root_path(self) -> str: ...

    @property
    def compiled_plan_id(self) -> str: ...

    @property
    def node_plan_revision_id(self) -> str: ...

    @property
    def assignment_work_plan_revision(self) -> int: ...

    @property
    def source_outcome(self) -> str: ...

    @property
    def raw_provider_kind(self) -> str | None: ...

    @property
    def opened_reason(self) -> str: ...

    @property
    def prompt(self) -> BoundaryPromptSnapshot: ...

    @property
    def expected_flow_status(self) -> Literal["running", "paused"]: ...

    @property
    def expected_pause_reason(self) -> str | None: ...


async def commit_boundary_dispatch_if_current(
    session: AsyncSession,
    *,
    snapshot: BoundaryOpeningCommitSnapshot,
    prepared: PreparedDispatchRequest,
    resume_event: TaskResumeEventBasis | None = None,
) -> bool:
    prompt = snapshot.prompt
    claimed = await session.scalar(
        update(AcceptedBoundaryModel)
        .where(
            AcceptedBoundaryModel.source_dispatch_id == prompt.predecessor_dispatch_id,
            AcceptedBoundaryModel.task_id == prompt.task_id,
            AcceptedBoundaryModel.flow_id == prompt.flow_id,
            AcceptedBoundaryModel.outcome == snapshot.source_outcome,
            AcceptedBoundaryModel.committed_at == snapshot.source_committed_at,
            AcceptedBoundaryModel.successor_dispatch_id.is_(None),
        )
        .values(successor_dispatch_id=prepared.dispatch_id)
        .returning(AcceptedBoundaryModel.accepted_boundary_id)
    )
    if claimed is None:
        await session.rollback()
        return False
    flow_predicates: list[ColumnElement[bool]] = [
        FlowModel.flow_id == prompt.flow_id,
        FlowModel.task_id == prompt.task_id,
        FlowModel.compiled_plan_id == snapshot.compiled_plan_id,
        FlowModel.status == snapshot.expected_flow_status,
        FlowModel.active_flow_revision_id == prompt.flow_revision_id,
        FlowModel.current_dispatch_id.is_(None),
        FlowModel.waiting_cause == "none",
        FlowModel.control_revision == snapshot.flow_control_revision,
        _boundary_target_is_current(snapshot),
    ]
    values: dict[str, object] = {
        "current_dispatch_id": prepared.dispatch_id,
        "updated_at": prepared.due_at,
    }
    if snapshot.expected_flow_status == "paused":
        flow_predicates.append(FlowModel.pause_reason == snapshot.expected_pause_reason)
        values.update(
            status="running",
            pause_reason=None,
            pause_details=None,
            paused_at=None,
            paused_by_actor_ref=None,
            control_revision=FlowModel.control_revision + 1,
        )
    updated_flow = await session.scalar(
        update(FlowModel).where(*flow_predicates).values(**values).returning(FlowModel.flow_id)
    )
    if updated_flow is None:
        await session.rollback()
        return False
    await stage_starting_dispatch(
        session,
        basis=StartingDispatchBasis(
            task_id=prompt.task_id,
            flow_id=prompt.flow_id,
            assignment_id=prompt.assignment_id,
            attempt_id=prompt.attempt_id,
            node_key=prompt.node_key,
            opened_reason=snapshot.opened_reason,
            predecessor_dispatch_id=prompt.predecessor_dispatch_id,
            flow_start_source_flow_id=None,
            resume_event=resume_event,
        ),
        prepared=prepared,
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return True


async def pause_failed_boundary_continuation(
    session: AsyncSession,
    *,
    source_dispatch_id: str,
    paused_at: datetime,
    failure_code: str,
) -> None:
    source_is_unconsumed = exists().where(
        AcceptedBoundaryModel.flow_id == FlowModel.flow_id,
        AcceptedBoundaryModel.task_id == FlowModel.task_id,
        AcceptedBoundaryModel.source_dispatch_id == source_dispatch_id,
        AcceptedBoundaryModel.successor_dispatch_id.is_(None),
    )
    await session.execute(
        update(FlowModel)
        .where(
            FlowModel.status == "running",
            FlowModel.current_dispatch_id.is_(None),
            FlowModel.waiting_cause == "none",
            source_is_unconsumed,
        )
        .values(
            status="paused",
            pause_reason="runtime_transition_failed",
            pause_details={
                "source": "accepted_boundary",
                "source_dispatch_id": source_dispatch_id,
                "failure_code": failure_code,
            },
            paused_at=paused_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=FlowModel.control_revision + 1,
            updated_at=paused_at,
        )
    )
    await session.commit()


def _boundary_target_is_current(
    snapshot: BoundaryOpeningCommitSnapshot,
) -> ColumnElement[bool]:
    prompt = snapshot.prompt
    return (
        exists().where(
            DispatchTurnModel.dispatch_id == prompt.predecessor_dispatch_id,
            DispatchTurnModel.task_id == prompt.task_id,
            DispatchTurnModel.flow_id == prompt.flow_id,
            DispatchTurnModel.status == "closed",
            DispatchTurnModel.closed_reason == "boundary",
        )
        & exists().where(
            FlowNodeModel.flow_id == prompt.flow_id,
            FlowNodeModel.flow_revision_id == prompt.flow_revision_id,
            FlowNodeModel.node_key == prompt.node_key,
            FlowNodeModel.structural_kind == prompt.node_kind,
            FlowNodeModel.state == "running",
            FlowNodeModel.current_assignment_id == prompt.assignment_id,
            FlowNodeModel.provider_kind == snapshot.raw_provider_kind,
        )
        & exists().where(
            NodePlanRevisionModel.node_plan_revision_id == snapshot.node_plan_revision_id,
            NodePlanRevisionModel.flow_id == prompt.flow_id,
            NodePlanRevisionModel.flow_revision_id == prompt.flow_revision_id,
            NodePlanRevisionModel.provider_kind == snapshot.raw_provider_kind,
        )
        & exists().where(
            AssignmentModel.assignment_id == prompt.assignment_id,
            AssignmentModel.task_id == prompt.task_id,
            AssignmentModel.flow_id == prompt.flow_id,
            AssignmentModel.flow_revision_id == prompt.flow_revision_id,
            AssignmentModel.node_key == prompt.node_key,
            AssignmentModel.current_attempt_id == prompt.attempt_id,
            AssignmentModel.work_plan_revision == snapshot.assignment_work_plan_revision,
            AssignmentModel.superseded_at.is_(None),
        )
        & exists().where(
            AttemptModel.attempt_id == prompt.attempt_id,
            AttemptModel.assignment_id == prompt.assignment_id,
            AttemptModel.task_id == prompt.task_id,
            AttemptModel.flow_id == prompt.flow_id,
            AttemptModel.node_key == prompt.node_key,
            AttemptModel.status == "running",
        )
        & exists().where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.task_root_path == snapshot.task_root_path,
            TaskModel.title == prompt.task_title,
            TaskModel.summary == prompt.task_summary,
        )
        & exists().where(
            WorkspaceBindingModel.task_id == prompt.task_id,
            WorkspaceBindingModel.normalized_root_path == snapshot.workspace_root_path,
        )
    )


__all__ = [
    "BoundaryOpeningCommitSnapshot",
    "commit_boundary_dispatch_if_current",
    "pause_failed_boundary_continuation",
]

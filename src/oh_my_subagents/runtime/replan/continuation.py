from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from oh_my_subagents.persistence.models import ReplanTransitionModel
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts import ReplanSuccess
from oh_my_subagents.runtime.contracts.prompt import (
    StructuralReplanResult,
    StructuralReplanSource,
    StructuralReplanTrigger,
)
from oh_my_subagents.runtime.dispatch.opening import TaskResumeEventBasis
from oh_my_subagents.runtime.dispatch.ordinary_context import OrdinaryContinuationBasis
from oh_my_subagents.runtime.dispatch.ordinary_continuation import (
    OrdinaryDispatchSnapshot,
    OrdinaryOpeningResult,
    open_ordinary_successor,
)
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
)
from oh_my_subagents.runtime.post_commit import ReplanCommitted
from oh_my_subagents.runtime.projection.materialization import project_workflow_manifest
from oh_my_subagents.runtime.projection.signals import WorkflowManifestProjection

type ReplanCommittedHandler = Callable[[AsyncSession, ReplanCommitted], Awaitable[None]]

_FAILURE_DETAIL_LIMIT = 1024


def create_replan_committed_handler(
    dependencies: DispatchOpeningDependencies,
) -> ReplanCommittedHandler:
    """Create the manifest-first repairable successor handler."""

    async def handle(session: AsyncSession, signal: ReplanCommitted) -> None:
        await continue_committed_replan(
            session,
            transition_id=signal.transition_id,
            dependencies=dependencies,
        )

    return handle


async def continue_committed_replan(
    session: AsyncSession,
    *,
    transition_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_task_status: Literal["running", "paused"] = "running",
    expected_control_revision: int | None = None,
    resume_event: TaskResumeEventBasis | None = None,
) -> OrdinaryOpeningResult:
    """Repair the manifest barrier and open at most one exact successor Dispatch."""

    if not await ensure_replan_manifest_current(session, transition_id):
        return OrdinaryOpeningResult(outcome="paused")
    return await open_ordinary_successor(
        session,
        source_id=transition_id,
        dependencies=dependencies,
        read_source=read_replan_continuation_basis,
        claim_source=claim_replan_continuation,
        record_failure=_record_opening_failure,
        default_failure_code="replan_dispatch_preparation_failed",
        expected_task_status=expected_task_status,
        expected_control_revision=expected_control_revision,
        should_resume_task=expected_task_status == "paused",
        resume_event=resume_event,
    )


async def ensure_replan_manifest_current(
    session: AsyncSession,
    transition_id: str,
) -> bool:
    transition = await session.get(ReplanTransitionModel, transition_id)
    if transition is None or transition.successor_state in {"opened", "cancelled"}:
        await session.rollback()
        return transition is not None and transition.successor_state == "opened"
    if transition.manifest_state == "current":
        await session.rollback()
        return True
    try:
        projected = await project_workflow_manifest(
            session,
            WorkflowManifestProjection(
                task_id=transition.task_id,
                team_revision_id=transition.successor_team_revision_id,
            ),
        )
    except Exception as exc:
        await session.rollback()
        await _record_manifest_failure(
            session,
            transition_id,
            code="replan_manifest_projection_failed",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return False
    await session.rollback()
    if not projected:
        await _record_manifest_failure(
            session,
            transition_id,
            code="replan_manifest_not_current",
            detail="The successor Team was no longer current during manifest projection.",
        )
        return False
    return await _mark_manifest_current(session, transition_id)


async def read_replan_continuation_basis(
    session: AsyncSession,
    transition_id: str,
) -> OrdinaryContinuationBasis | None:
    transition = await session.scalar(
        select(ReplanTransitionModel)
        .options(raiseload("*"))
        .where(
            ReplanTransitionModel.replan_transition_id == transition_id,
            ReplanTransitionModel.manifest_state == "current",
            ReplanTransitionModel.successor_state.in_(("pending", "opening_failed")),
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
    )
    if transition is None:
        return None
    result = ReplanSuccess.model_validate(transition.committed_result_json)
    if transition.operation != result.operation:
        raise ValueError("replan transition operation does not match its committed result")
    return OrdinaryContinuationBasis(
        task_id=transition.task_id,
        assignment_id=transition.assignment_id,
        attempt_id=transition.attempt_id,
        source_dispatch_id=transition.source_dispatch_id,
        source_dispatch_closed_reason="structural_replan",
        opened_reason="structural_replan",
        trigger=StructuralReplanTrigger(
            source=StructuralReplanSource(
                source_dispatch_id=transition.source_dispatch_id,
                operation=result.operation,
            ),
            result=StructuralReplanResult(replan=result),
        ),
        continuation_source_id=transition.replan_transition_id,
    )


async def claim_replan_continuation(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    now = prepared.due_at
    transition_id = _transition_id_from_snapshot(snapshot)
    claimed = await session.scalar(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.replan_transition_id == transition_id,
            ReplanTransitionModel.source_dispatch_id == snapshot.basis.source_dispatch_id,
            ReplanTransitionModel.successor_team_revision_id == snapshot.prompt.team_revision_id,
            ReplanTransitionModel.manifest_state == "current",
            ReplanTransitionModel.successor_state.in_(("pending", "opening_failed")),
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
        .values(
            successor_state="opened",
            successor_dispatch_id=prepared.dispatch_id,
            successor_opened_at=now,
            failure_code=None,
            failure_detail=None,
            updated_at=now,
        )
        .returning(ReplanTransitionModel.replan_transition_id)
    )
    return claimed is not None


async def _mark_manifest_current(session: AsyncSession, transition_id: str) -> bool:
    now = utc_now()
    claimed = await session.scalar(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.replan_transition_id == transition_id,
            ReplanTransitionModel.manifest_state.in_(("pending", "repair_required")),
            ReplanTransitionModel.successor_state == "blocked",
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
        .values(
            manifest_state="current",
            successor_state="pending",
            failure_code=None,
            failure_detail=None,
            manifest_current_at=now,
            updated_at=now,
        )
        .returning(ReplanTransitionModel.replan_transition_id)
    )
    if claimed is None:
        current = await session.get(ReplanTransitionModel, transition_id)
        await session.rollback()
        return current is not None and current.manifest_state == "current"
    await session.commit()
    return True


async def _record_manifest_failure(
    session: AsyncSession,
    transition_id: str,
    *,
    code: str,
    detail: str,
) -> None:
    now = utc_now()
    await session.execute(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.replan_transition_id == transition_id,
            ReplanTransitionModel.successor_dispatch_id.is_(None),
            ReplanTransitionModel.successor_state.not_in(("opened", "cancelled")),
        )
        .values(
            manifest_state="repair_required",
            successor_state="blocked",
            failure_code=code[:128],
            failure_detail=detail[:_FAILURE_DETAIL_LIMIT],
            updated_at=now,
        )
    )
    await session.commit()


async def _record_opening_failure(
    session: AsyncSession,
    transition_id: str,
    failed_at: datetime,
    failure_code: str,
) -> tuple[str, ...]:
    await session.execute(
        update(ReplanTransitionModel)
        .where(
            ReplanTransitionModel.replan_transition_id == transition_id,
            ReplanTransitionModel.manifest_state == "current",
            ReplanTransitionModel.successor_state.in_(("pending", "opening_failed")),
            ReplanTransitionModel.successor_dispatch_id.is_(None),
        )
        .values(
            successor_state="opening_failed",
            failure_code=failure_code[:128],
            failure_detail="Successor Dispatch preparation failed."[:_FAILURE_DETAIL_LIMIT],
            updated_at=failed_at,
        )
    )
    await session.commit()
    return ()


def _transition_id_from_snapshot(snapshot: OrdinaryDispatchSnapshot) -> str:
    trigger = snapshot.basis.trigger
    if not isinstance(trigger, StructuralReplanTrigger):
        raise TypeError("replan continuation requires a structural_replan trigger")
    transition_id = snapshot.basis.continuation_source_id
    if transition_id is None:
        raise TypeError("replan continuation is missing its transition identity")
    return transition_id


__all__ = [
    "ReplanCommittedHandler",
    "claim_replan_continuation",
    "continue_committed_replan",
    "create_replan_committed_handler",
    "ensure_replan_manifest_current",
    "read_replan_continuation_basis",
]

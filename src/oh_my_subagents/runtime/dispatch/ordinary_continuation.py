from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from oh_my_subagents.persistence.models import TaskModel
from oh_my_subagents.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from oh_my_subagents.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
    ordinary_context_is_current,
    read_ordinary_dispatch_snapshot,
)
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from oh_my_subagents.runtime.dispatch.prompt_snapshot import build_ordinary_dispatch_request
from oh_my_subagents.runtime.post_commit import DispatchCleanupRequested, DispatchStartDue
from oh_my_subagents.runtime.providers import ProviderResolutionError

type OrdinarySourceReader = Callable[
    [AsyncSession, str], Awaitable[OrdinaryContinuationBasis | None]
]
type OrdinarySourceClaim = Callable[
    [AsyncSession, OrdinaryDispatchSnapshot, PreparedDispatchRequest],
    Awaitable[bool],
]
type OrdinaryFailureRecorder = Callable[
    [AsyncSession, str, datetime, str],
    Awaitable[tuple[str, ...]],
]


@dataclass(frozen=True, slots=True)
class OrdinaryOpeningResult:
    outcome: Literal["opened", "skipped", "paused"]
    dispatch_id: str | None = None


async def open_ordinary_successor(
    session: AsyncSession,
    *,
    source_id: str,
    dependencies: DispatchOpeningDependencies,
    read_source: OrdinarySourceReader,
    claim_source: OrdinarySourceClaim,
    record_failure: OrdinaryFailureRecorder,
    default_failure_code: str,
    expected_task_status: Literal["running", "paused"] = "running",
    expected_control_revision: int | None = None,
    should_resume_task: bool = False,
    resume_event: TaskResumeEventBasis | None = None,
) -> OrdinaryOpeningResult:
    """Prepare and conditionally open one runnable exact-source successor."""

    dispatch_id = f"dispatch.{uuid4().hex}"
    due_at = dependencies.clock()
    try:
        basis = await read_source(session, source_id)
        if basis is None:
            await session.rollback()
            return OrdinaryOpeningResult(outcome="skipped")
        snapshot = await read_ordinary_dispatch_snapshot(
            session,
            basis=basis,
            dispatch_id=dispatch_id,
            dependencies=dependencies,
            expected_task_status=expected_task_status,
            expected_control_revision=expected_control_revision,
        )
        if snapshot is None:
            await session.rollback()
            return OrdinaryOpeningResult(outcome="skipped")
        request = build_ordinary_dispatch_request(snapshot.prompt)
        await session.rollback()
        prepared = prepare_dispatch_request(
            dependencies=dependencies,
            dispatch_id=dispatch_id,
            due_at=due_at,
            provider=snapshot.provider,
            capabilities=snapshot.capabilities,
            request=request,
        )
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = str(getattr(exc, "code", default_failure_code))
        closed_dispatch_ids = await record_failure(session, source_id, due_at, failure_code)
        for closed_dispatch_id in closed_dispatch_ids:
            try:
                dependencies.post_commit_publisher.publish(
                    DispatchCleanupRequested(closed_dispatch_id)
                )
            except Exception:
                pass
        return OrdinaryOpeningResult(outcome="paused")

    committed = await commit_ordinary_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        claim_source=claim_source,
        should_resume_task=should_resume_task,
        resume_event=resume_event,
    )
    if not committed:
        return OrdinaryOpeningResult(outcome="skipped")
    publish_dispatch_start_due(dependencies, prepared)
    return OrdinaryOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def commit_ordinary_dispatch_if_current(
    session: AsyncSession,
    *,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
    claim_source: OrdinarySourceClaim,
    should_resume_task: bool,
    resume_event: TaskResumeEventBasis | None = None,
) -> bool:
    """Claim the Task, local source, and same-Attempt successor atomically."""

    task_predicates: list[ColumnElement[bool]] = [
        TaskModel.task_id == snapshot.prompt.task_id,
        TaskModel.root_assignment_id.is_not(None),
        TaskModel.status == snapshot.expected_task_status,
        TaskModel.current_team_revision_id == snapshot.prompt.team_revision_id,
        TaskModel.control_revision == snapshot.task_control_revision,
        ordinary_context_is_current(snapshot),
    ]
    if snapshot.expected_task_status == "paused":
        task_predicates.append(TaskModel.pause_reason == snapshot.expected_pause_reason)
    values: dict[str, object] = {
        "updated_at": TaskModel.updated_at,
    }
    if should_resume_task:
        values.update(
            status="running",
            pause_reason=None,
            pause_details=None,
            paused_at=None,
            paused_by_actor_ref=None,
            control_revision=TaskModel.control_revision + 1,
        )
    task_id = await session.scalar(
        update(TaskModel).where(*task_predicates).values(**values).returning(TaskModel.task_id)
    )
    if task_id is None:
        await session.rollback()
        return False
    if not await claim_source(session, snapshot, prepared):
        await session.rollback()
        return False
    await stage_starting_dispatch(
        session,
        basis=StartingDispatchBasis(
            task_id=snapshot.prompt.task_id,
            assignment_id=snapshot.prompt.assignment_id,
            team_revision_id=snapshot.prompt.team_revision_id,
            member_id=snapshot.prompt.member_id,
            member_configuration_id=snapshot.prompt.member_configuration_id,
            member_branch_basis_id=snapshot.prompt.member_branch_basis_id,
            attempt_id=snapshot.prompt.attempt_id,
            opened_reason=snapshot.basis.opened_reason,
            predecessor_dispatch_id=snapshot.prompt.predecessor_dispatch_id,
            task_start_source_task_id=None,
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


def publish_dispatch_start_due(
    dependencies: DispatchOpeningDependencies,
    prepared: PreparedDispatchRequest,
) -> None:
    """Attempt the disposable provider-start hint after D2 commit."""

    try:
        dependencies.post_commit_publisher.publish(
            DispatchStartDue(
                dispatch_id=prepared.dispatch_id,
                provider_start_revision=0,
                due_at=prepared.due_at,
            )
        )
    except Exception:
        pass


__all__ = [
    "OrdinaryFailureRecorder",
    "OrdinaryOpeningResult",
    "OrdinarySourceClaim",
    "OrdinarySourceReader",
    "commit_ordinary_dispatch_if_current",
    "open_ordinary_successor",
    "publish_dispatch_start_due",
]

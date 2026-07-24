"""Paused Task continuation orchestration."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.contracts.primitives import TaskEventSource
from banksia.runtime.dispatch.currentness import AttemptDispatchConflictError
from banksia.runtime.dispatch.opening import TaskResumeEventBasis
from banksia.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.launch.continuation import continue_paused_root_dispatch
from banksia.runtime.providers import ProviderResolutionError
from banksia.runtime.task_control.paused_continuation.contracts import (
    OperatorContinueSource,
    PausedAttemptLane,
    PausedTaskContinuationPlan,
    PausedTaskContinuationResult,
    paused_continuation_conflict,
    paused_continuation_preparation_error,
)
from banksia.runtime.task_control.paused_continuation.persistence import (
    commit_paused_continuations,
    prepare_paused_continuations,
)
from banksia.runtime.task_control.paused_continuation.sources import (
    claim_operator_continue_tail,
    read_paused_task_continuation_plan,
    repair_paused_replan_manifests,
)


async def continue_paused_task(
    session: AsyncSession,
    *,
    task_id: str,
    expected_team_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis | None = None,
) -> PausedTaskContinuationResult:
    """Resume every runnable Attempt lane from one exact paused Task snapshot."""

    active_resume_event = resume_event or TaskResumeEventBasis(
        control_revision=expected_control_revision + 1,
        actor_ref=None,
        event_source=TaskEventSource.CONTROL_API,
    )
    try:
        await repair_paused_replan_manifests(
            session,
            task_id=task_id,
            expected_team_revision_id=expected_team_revision_id,
            expected_control_revision=expected_control_revision,
        )
        plan = await read_paused_task_continuation_plan(
            session,
            task_id=task_id,
            expected_team_revision_id=expected_team_revision_id,
            expected_control_revision=expected_control_revision,
        )
        if plan.has_unconsumed_task_start:
            return await _continue_paused_root(
                session,
                plan=plan,
                dependencies=dependencies,
                resume_event=active_resume_event,
            )
        prepared = await prepare_paused_continuations(
            session,
            plan=plan,
            dependencies=dependencies,
        )
        await commit_paused_continuations(
            session,
            plan=plan,
            prepared=prepared,
            resume_event=active_resume_event,
            resumed_at=dependencies.clock(),
        )
    except RuntimeOperationError:
        await session.rollback()
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        raise paused_continuation_preparation_error(exc) from exc
    except AttemptDispatchConflictError as exc:
        await session.rollback()
        raise paused_continuation_conflict(
            "another controller transition won during continue"
        ) from exc

    for item in prepared:
        publish_dispatch_start_due(dependencies, item.prepared)
    return PausedTaskContinuationResult(
        outcome="resumed",
        dispatch_ids=tuple(item.prepared.dispatch_id for item in prepared),
    )


async def _continue_paused_root(
    session: AsyncSession,
    *,
    plan: PausedTaskContinuationPlan,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis,
) -> PausedTaskContinuationResult:
    root_result = await continue_paused_root_dispatch(
        session,
        task_id=plan.task.task_id,
        expected_team_revision_id=plan.task.current_team_revision_id,
        expected_control_revision=plan.task.control_revision,
        dependencies=dependencies,
        resume_event=resume_event,
    )
    if root_result.outcome != "opened" or root_result.dispatch_id is None:
        raise paused_continuation_conflict("paused root source did not open its successor")
    return PausedTaskContinuationResult(
        outcome="resumed",
        dispatch_ids=(root_result.dispatch_id,),
    )


__all__ = [
    "OperatorContinueSource",
    "PausedAttemptLane",
    "PausedTaskContinuationPlan",
    "PausedTaskContinuationResult",
    "claim_operator_continue_tail",
    "continue_paused_task",
    "read_paused_task_continuation_plan",
]

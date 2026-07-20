from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import FlowModel, FlowStartSourceModel
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from autoclaw.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due
from autoclaw.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from autoclaw.runtime.dispatch.prompt_snapshot import build_root_dispatch_request
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.launch.root_source import (
    RootOpeningSnapshot,
    read_root_opening_snapshot,
    root_context_is_current,
)
from autoclaw.runtime.post_commit import FlowStartCommitted
from autoclaw.runtime.providers import ProviderResolutionError

type FlowStartHandler = Callable[[AsyncSession, FlowStartCommitted], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class FlowStartOpeningResult:
    outcome: Literal["opened", "skipped", "paused"]
    dispatch_id: str | None = None


def create_flow_start_handler(
    dependencies: DispatchOpeningDependencies,
) -> FlowStartHandler:
    async def handle(session: AsyncSession, signal: FlowStartCommitted) -> None:
        await open_root_dispatch(session, signal=signal, dependencies=dependencies)

    return handle


async def open_root_dispatch(
    session: AsyncSession,
    *,
    signal: FlowStartCommitted,
    dependencies: DispatchOpeningDependencies,
) -> FlowStartOpeningResult:
    transition_at = dependencies.clock()
    try:
        candidate = await _prepare_root_dispatch(
            session,
            flow_id=signal.flow_id,
            dependencies=dependencies,
            expected_flow_status="running",
            expected_active_flow_revision_id=None,
            expected_control_revision=None,
            due_at=transition_at,
        )
        if candidate is None:
            await session.rollback()
            return FlowStartOpeningResult(outcome="skipped")
        snapshot, prepared = candidate
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = getattr(exc, "code", "root_dispatch_preparation_failed")
        await _pause_failed_flow_start(
            session,
            flow_id=signal.flow_id,
            paused_at=transition_at,
            failure_code=str(failure_code),
        )
        return FlowStartOpeningResult(outcome="paused")

    if not await _commit_root_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
    ):
        return FlowStartOpeningResult(outcome="skipped")
    publish_dispatch_start_due(dependencies, prepared)
    return FlowStartOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def continue_paused_root_dispatch(
    session: AsyncSession,
    *,
    flow_id: str,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis,
) -> FlowStartOpeningResult:
    """Directly resume one paused, unconsumed flow-start source."""

    try:
        candidate = await _prepare_root_dispatch(
            session,
            flow_id=flow_id,
            dependencies=dependencies,
            expected_flow_status="paused",
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
            due_at=dependencies.clock(),
        )
        if candidate is None:
            raise _root_continue_conflict("paused flow start is no longer current")
        snapshot, prepared = candidate
    except RuntimeOperationError:
        await session.rollback()
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        code = str(getattr(exc, "code", "operator_continue_preparation_failed"))
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary=f"operator continue preparation failed: {code}",
            is_retryable=False,
            suggested_next_step="Repair the exact source or provider route, then retry continue.",
        ) from exc

    if not await _commit_root_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        resume_event=resume_event,
    ):
        raise _root_continue_conflict("another controller transition won during continue")
    publish_dispatch_start_due(dependencies, prepared)
    return FlowStartOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def _prepare_root_dispatch(
    session: AsyncSession,
    *,
    flow_id: str,
    dependencies: DispatchOpeningDependencies,
    expected_flow_status: Literal["running", "paused"],
    expected_active_flow_revision_id: str | None,
    expected_control_revision: int | None,
    due_at: datetime,
) -> tuple[RootOpeningSnapshot, PreparedDispatchRequest] | None:
    dispatch_id = f"dispatch.{uuid4().hex}"
    snapshot = await read_root_opening_snapshot(
        session,
        flow_id=flow_id,
        dispatch_id=dispatch_id,
        dependencies=dependencies,
        expected_flow_status=expected_flow_status,
        expected_active_flow_revision_id=expected_active_flow_revision_id,
        expected_control_revision=expected_control_revision,
    )
    if snapshot is None:
        return None
    request = build_root_dispatch_request(snapshot.prompt, trigger=snapshot.trigger)
    await session.rollback()
    prepared = prepare_dispatch_request(
        dependencies=dependencies,
        paths=snapshot.paths,
        dispatch_id=dispatch_id,
        due_at=due_at,
        provider=snapshot.provider,
        capabilities=snapshot.capabilities,
        request=request,
    )
    return snapshot, prepared


async def _commit_root_dispatch_if_current(
    session: AsyncSession,
    *,
    snapshot: RootOpeningSnapshot,
    prepared: PreparedDispatchRequest,
    resume_event: TaskResumeEventBasis | None = None,
) -> bool:
    prompt = snapshot.prompt
    claimed = await session.scalar(
        update(FlowStartSourceModel)
        .where(
            FlowStartSourceModel.flow_id == prompt.flow_id,
            FlowStartSourceModel.task_id == prompt.task_id,
            FlowStartSourceModel.successor_dispatch_id.is_(None),
            FlowStartSourceModel.committed_at == snapshot.source_committed_at,
        )
        .values(successor_dispatch_id=prepared.dispatch_id)
        .returning(FlowStartSourceModel.flow_id)
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
        root_context_is_current(snapshot),
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
            predecessor_dispatch_id=None,
            flow_start_source_flow_id=prompt.flow_id,
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


async def _pause_failed_flow_start(
    session: AsyncSession,
    *,
    flow_id: str,
    paused_at: datetime,
    failure_code: str,
) -> None:
    source_is_unconsumed = exists().where(
        FlowStartSourceModel.flow_id == FlowModel.flow_id,
        FlowStartSourceModel.task_id == FlowModel.task_id,
        FlowStartSourceModel.successor_dispatch_id.is_(None),
    )
    await session.execute(
        update(FlowModel)
        .where(
            FlowModel.flow_id == flow_id,
            FlowModel.status == "running",
            FlowModel.current_dispatch_id.is_(None),
            FlowModel.waiting_cause == "none",
            source_is_unconsumed,
        )
        .values(
            status="paused",
            pause_reason="runtime_transition_failed",
            pause_details={"source": "flow_start", "failure_code": failure_code},
            paused_at=paused_at,
            paused_by_actor_ref="controller.runtime",
            control_revision=FlowModel.control_revision + 1,
            updated_at=paused_at,
        )
    )
    await session.commit()


def _root_continue_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the flow and retry only from the same paused revision.",
        status_code_override=409,
    )


__all__ = [
    "FlowStartHandler",
    "FlowStartOpeningResult",
    "continue_paused_root_dispatch",
    "create_flow_start_handler",
    "open_root_dispatch",
]

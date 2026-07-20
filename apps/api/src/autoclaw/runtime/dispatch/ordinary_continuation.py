from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import FlowModel
from autoclaw.runtime.dispatch.opening import (
    StartingDispatchBasis,
    TaskResumeEventBasis,
    stage_starting_dispatch,
)
from autoclaw.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
    ordinary_context_is_current,
    read_ordinary_dispatch_snapshot,
)
from autoclaw.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from autoclaw.runtime.dispatch.prompt_snapshot import build_ordinary_dispatch_request
from autoclaw.runtime.post_commit import DispatchStartDue
from autoclaw.runtime.providers import ProviderResolutionError

type OrdinarySourceReader = Callable[
    [AsyncSession, str], Awaitable[OrdinaryContinuationBasis | None]
]
type OrdinarySourceClaim = Callable[
    [AsyncSession, OrdinaryDispatchSnapshot, PreparedDispatchRequest],
    Awaitable[bool],
]
type OrdinaryFailureRecorder = Callable[[AsyncSession, str, datetime, str], Awaitable[None]]


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
            expected_flow_status="running",
        )
        if snapshot is None:
            await session.rollback()
            return OrdinaryOpeningResult(outcome="skipped")
        request = build_ordinary_dispatch_request(snapshot.prompt)
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
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        failure_code = str(getattr(exc, "code", default_failure_code))
        await record_failure(session, source_id, due_at, failure_code)
        return OrdinaryOpeningResult(outcome="paused")

    committed = await commit_ordinary_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        claim_source=claim_source,
        should_resume_flow=False,
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
    should_resume_flow: bool,
    resume_event: TaskResumeEventBasis | None = None,
) -> bool:
    """Claim one source and commit its flow pointer plus starting D2 atomically."""

    if not await claim_source(session, snapshot, prepared):
        await session.rollback()
        return False
    flow_predicates: list[ColumnElement[bool]] = [
        FlowModel.flow_id == snapshot.prompt.flow_id,
        FlowModel.task_id == snapshot.prompt.task_id,
        FlowModel.compiled_plan_id == snapshot.compiled_plan_id,
        FlowModel.status == snapshot.expected_flow_status,
        FlowModel.active_flow_revision_id == snapshot.prompt.flow_revision_id,
        FlowModel.current_dispatch_id.is_(None),
        FlowModel.waiting_cause == "none",
        FlowModel.control_revision == snapshot.flow_control_revision,
        ordinary_context_is_current(snapshot),
    ]
    if snapshot.expected_flow_status == "paused":
        flow_predicates.append(FlowModel.pause_reason == snapshot.expected_pause_reason)
    values: dict[str, object] = {
        "current_dispatch_id": prepared.dispatch_id,
        "updated_at": prepared.due_at,
    }
    if should_resume_flow:
        values.update(
            status="running",
            pause_reason=None,
            pause_details=None,
            paused_at=None,
            paused_by_actor_ref=None,
            control_revision=FlowModel.control_revision + 1,
        )
    flow_id = await session.scalar(
        update(FlowModel).where(*flow_predicates).values(**values).returning(FlowModel.flow_id)
    )
    if flow_id is None:
        await session.rollback()
        return False
    await stage_starting_dispatch(
        session,
        basis=StartingDispatchBasis(
            task_id=snapshot.prompt.task_id,
            flow_id=snapshot.prompt.flow_id,
            assignment_id=snapshot.prompt.assignment_id,
            attempt_id=snapshot.prompt.attempt_id,
            node_key=snapshot.prompt.node_key,
            opened_reason=snapshot.basis.opened_reason,
            predecessor_dispatch_id=snapshot.prompt.predecessor_dispatch_id,
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

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, raiseload

from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowStartSourceModel,
    FlowWaitModel,
    HumanRequestModel,
)
from autoclaw.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from autoclaw.runtime.boundary import continue_paused_boundary
from autoclaw.runtime.command_run.continuation import (
    claim_command_run_continuation,
    command_run_continuation_basis,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.contracts.primitives import TaskEventSource
from autoclaw.runtime.contracts.prompt import OperatorContinueTrigger
from autoclaw.runtime.dispatch.opening import TaskResumeEventBasis
from autoclaw.runtime.dispatch.ordinary_context import (
    OrdinaryContinuationBasis,
    OrdinaryDispatchSnapshot,
    read_ordinary_dispatch_snapshot,
)
from autoclaw.runtime.dispatch.ordinary_continuation import (
    OrdinaryOpeningResult,
    commit_ordinary_dispatch_if_current,
    publish_dispatch_start_due,
)
from autoclaw.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
    prepare_dispatch_request,
)
from autoclaw.runtime.dispatch.prompt_snapshot import build_ordinary_dispatch_request
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.human_request.continuation import (
    claim_human_request_continuation,
    human_request_continuation_basis,
)
from autoclaw.runtime.launch.continuation import continue_paused_root_dispatch
from autoclaw.runtime.providers import ProviderResolutionError

type OperatorContinueSourceClaim = Callable[
    [AsyncSession, OrdinaryDispatchSnapshot, PreparedDispatchRequest],
    Awaitable[bool],
]


@dataclass(frozen=True, slots=True)
class OperatorContinueSource:
    basis: OrdinaryContinuationBasis
    claim: OperatorContinueSourceClaim


@dataclass(frozen=True, slots=True)
class OperatorFlowStartSource:
    flow_id: str


@dataclass(frozen=True, slots=True)
class OperatorBoundarySource:
    source_dispatch_id: str


type OperatorContinueSelection = (
    OperatorContinueSource | OperatorFlowStartSource | OperatorBoundarySource
)


async def continue_paused_flow(
    session: AsyncSession,
    *,
    task_id: str,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis | None = None,
) -> OrdinaryOpeningResult:
    """Directly prepare and commit one exact paused-flow continuation."""

    active_resume_event = resume_event or TaskResumeEventBasis(
        control_revision=expected_control_revision + 1,
        actor_ref=None,
        event_source=TaskEventSource.CONTROL_API,
    )
    try:
        source = await read_operator_continue_source(
            session,
            task_id=task_id,
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
        )
        if isinstance(source, OperatorFlowStartSource):
            root_result = await continue_paused_root_dispatch(
                session,
                flow_id=source.flow_id,
                expected_active_flow_revision_id=expected_active_flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=dependencies,
                resume_event=active_resume_event,
            )
            return OrdinaryOpeningResult(
                outcome=root_result.outcome,
                dispatch_id=root_result.dispatch_id,
            )
        if isinstance(source, OperatorBoundarySource):
            boundary_result = await continue_paused_boundary(
                session,
                source_dispatch_id=source.source_dispatch_id,
                expected_active_flow_revision_id=expected_active_flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=dependencies,
                resume_event=active_resume_event,
            )
            if boundary_result.outcome != "opened":
                raise _continue_conflict("paused boundary did not open its successor")
            return OrdinaryOpeningResult(
                outcome="opened",
                dispatch_id=boundary_result.dispatch_id,
            )
        return await _continue_ordinary_source(
            session,
            source=source,
            expected_control_revision=expected_control_revision,
            dependencies=dependencies,
            resume_event=active_resume_event,
        )
    except RuntimeOperationError:
        await session.rollback()
        raise
    except (ProviderResolutionError, ValueError, OSError) as exc:
        await session.rollback()
        raise _continue_preparation_error(exc) from exc


async def read_operator_continue_source(
    session: AsyncSession,
    *,
    task_id: str,
    expected_active_flow_revision_id: str,
    expected_control_revision: int,
) -> OperatorContinueSelection:
    """Select one exact retained source or lawful closed lineage tail."""

    flow = await session.scalar(
        select(FlowModel)
        .options(raiseload("*"))
        .where(
            FlowModel.task_id == task_id,
            FlowModel.status == "paused",
            FlowModel.active_flow_revision_id == expected_active_flow_revision_id,
            FlowModel.control_revision == expected_control_revision,
            FlowModel.current_dispatch_id.is_(None),
            FlowModel.waiting_cause == "none",
        )
    )
    if flow is None or flow.pause_reason not in {
        "paused_by_operator",
        "runtime_recovery_exhausted",
        "runtime_transition_failed",
    }:
        raise _continue_conflict("flow is not paused at the expected revision")
    if await _has_unresolved_external_source(session, flow.flow_id):
        raise _continue_conflict("flow still has an unresolved human request or command run")

    human_source = await _read_terminal_human_source(session, flow.flow_id)
    command_source = await _read_terminal_command_source(session, flow.flow_id)
    boundary_source = await _read_unconsumed_boundary_source(session, flow.flow_id)
    if sum(source is not None for source in (human_source, command_source, boundary_source)) > 1:
        raise _continue_conflict("paused flow has more than one retained continuation source")
    if human_source is not None:
        return OperatorContinueSource(
            basis=human_request_continuation_basis(
                human_source,
                opened_reason="operator_continue",
            ),
            claim=claim_human_request_continuation,
        )
    if command_source is not None:
        return OperatorContinueSource(
            basis=command_run_continuation_basis(
                command_source,
                opened_reason="operator_continue",
            ),
            claim=claim_command_run_continuation,
        )
    if boundary_source is not None:
        return OperatorBoundarySource(source_dispatch_id=boundary_source)
    source_dispatch = await _read_unconsumed_lineage_tail(session, flow)
    if source_dispatch is None:
        if await _has_unconsumed_flow_start(session, flow.flow_id):
            return OperatorFlowStartSource(flow_id=flow.flow_id)
        raise _continue_conflict("paused flow has no unconsumed continuation source")
    if source_dispatch.closed_reason is None:
        raise _continue_conflict("closed lineage tail is missing its close reason")
    return OperatorContinueSource(
        basis=OrdinaryContinuationBasis(
            task_id=source_dispatch.task_id,
            flow_id=source_dispatch.flow_id,
            assignment_id=source_dispatch.assignment_id,
            attempt_id=source_dispatch.attempt_id,
            source_dispatch_id=source_dispatch.dispatch_id,
            source_dispatch_closed_reason=source_dispatch.closed_reason,
            opened_reason="operator_continue",
            trigger=OperatorContinueTrigger(
                source_dispatch_id=source_dispatch.dispatch_id,
                control_revision=flow.control_revision,
                pause_reason=flow.pause_reason,
            ),
        ),
        claim=claim_operator_continue_tail,
    )


async def claim_operator_continue_tail(
    session: AsyncSession,
    snapshot: OrdinaryDispatchSnapshot,
    prepared: PreparedDispatchRequest,
) -> bool:
    """Recheck a source-free closed lineage tail before its successor commit."""

    del prepared
    source_dispatch_id = snapshot.basis.source_dispatch_id
    successor = aliased(DispatchTurnModel)
    is_available = await session.scalar(
        select(
            exists().where(
                DispatchTurnModel.dispatch_id == source_dispatch_id,
                DispatchTurnModel.task_id == snapshot.prompt.task_id,
                DispatchTurnModel.flow_id == snapshot.prompt.flow_id,
                DispatchTurnModel.assignment_id == snapshot.prompt.assignment_id,
                DispatchTurnModel.attempt_id == snapshot.prompt.attempt_id,
                DispatchTurnModel.status == "closed",
                DispatchTurnModel.closed_reason == snapshot.basis.source_dispatch_closed_reason,
                ~exists().where(successor.predecessor_dispatch_id == source_dispatch_id),
                ~exists().where(
                    AcceptedBoundaryModel.source_dispatch_id == source_dispatch_id,
                    AcceptedBoundaryModel.successor_dispatch_id.is_(None),
                ),
                ~exists().where(
                    HumanRequestModel.source_dispatch_id == source_dispatch_id,
                    HumanRequestModel.successor_dispatch_id.is_(None),
                ),
                ~exists().where(
                    CommandRunModel.source_dispatch_id == source_dispatch_id,
                    CommandRunModel.successor_dispatch_id.is_(None),
                ),
            )
        )
    )
    return bool(is_available)


async def _continue_ordinary_source(
    session: AsyncSession,
    *,
    source: OperatorContinueSource,
    expected_control_revision: int,
    dependencies: DispatchOpeningDependencies,
    resume_event: TaskResumeEventBasis,
) -> OrdinaryOpeningResult:
    dispatch_id = f"dispatch.{uuid4().hex}"
    due_at = dependencies.clock()
    snapshot = await read_ordinary_dispatch_snapshot(
        session,
        basis=source.basis,
        dispatch_id=dispatch_id,
        dependencies=dependencies,
        expected_flow_status="paused",
        expected_control_revision=expected_control_revision,
    )
    if snapshot is None:
        raise _continue_conflict("paused flow continuation is no longer current")
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
    committed = await commit_ordinary_dispatch_if_current(
        session,
        snapshot=snapshot,
        prepared=prepared,
        claim_source=source.claim,
        should_resume_flow=True,
        resume_event=resume_event,
    )
    if not committed:
        raise _continue_conflict("another controller transition won during continue")
    publish_dispatch_start_due(dependencies, prepared)
    return OrdinaryOpeningResult(outcome="opened", dispatch_id=prepared.dispatch_id)


async def _has_unresolved_external_source(session: AsyncSession, flow_id: str) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(FlowWaitModel.flow_id == flow_id)
                | exists().where(
                    HumanRequestModel.flow_id == flow_id,
                    HumanRequestModel.status == "open",
                )
                | exists().where(
                    CommandRunModel.flow_id == flow_id,
                    CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
                )
            )
        )
    )


async def _read_terminal_human_source(
    session: AsyncSession,
    flow_id: str,
) -> HumanRequestModel | None:
    rows = tuple(
        await session.scalars(
            select(HumanRequestModel)
            .options(raiseload("*"))
            .where(
                HumanRequestModel.flow_id == flow_id,
                HumanRequestModel.status.in_(("resolved", "timed_out", "cancelled")),
                HumanRequestModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise _continue_conflict("paused flow has multiple retained human-request sources")
    return rows[0] if rows else None


async def _read_terminal_command_source(
    session: AsyncSession,
    flow_id: str,
) -> CommandRunModel | None:
    rows = tuple(
        await session.scalars(
            select(CommandRunModel)
            .options(raiseload("*"))
            .where(
                CommandRunModel.flow_id == flow_id,
                CommandRunModel.state.in_(COMMAND_RUN_TERMINAL_STATE_VALUES),
                CommandRunModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise _continue_conflict("paused flow has multiple retained command-run sources")
    return rows[0] if rows else None


async def _read_unconsumed_lineage_tail(
    session: AsyncSession,
    flow: FlowModel,
) -> DispatchTurnModel | None:
    successor = aliased(DispatchTurnModel)
    rows = tuple(
        await session.scalars(
            select(DispatchTurnModel)
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.task_id == flow.task_id,
                DispatchTurnModel.flow_id == flow.flow_id,
                DispatchTurnModel.status == "closed",
                DispatchTurnModel.closed_reason.in_(("paused", "control_failed")),
                ~exists().where(successor.predecessor_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise _continue_conflict("paused flow has multiple closed lineage tails")
    return rows[0] if rows else None


async def _has_unconsumed_flow_start(session: AsyncSession, flow_id: str) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    FlowStartSourceModel.flow_id == flow_id,
                    FlowStartSourceModel.successor_dispatch_id.is_(None),
                )
            )
        )
    )


async def _read_unconsumed_boundary_source(
    session: AsyncSession,
    flow_id: str,
) -> str | None:
    source_ids = tuple(
        await session.scalars(
            select(AcceptedBoundaryModel.source_dispatch_id)
            .where(
                AcceptedBoundaryModel.flow_id == flow_id,
                AcceptedBoundaryModel.successor_dispatch_id.is_(None),
            )
            .limit(2)
        )
    )
    if len(source_ids) > 1:
        raise _continue_conflict("paused flow has multiple retained boundary sources")
    return source_ids[0] if source_ids else None


def _continue_preparation_error(exc: Exception) -> RuntimeOperationError:
    code = str(getattr(exc, "code", "operator_continue_preparation_failed"))
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=f"operator continue preparation failed: {code}",
        is_retryable=False,
        suggested_next_step="Repair the exact source or provider route, then retry continue.",
    )


def _continue_conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Reread the flow and retry only from the same paused revision.",
        status_code_override=409,
    )


__all__ = [
    "OperatorBoundarySource",
    "OperatorContinueSelection",
    "OperatorContinueSource",
    "OperatorFlowStartSource",
    "claim_operator_continue_tail",
    "continue_paused_flow",
    "read_operator_continue_source",
]

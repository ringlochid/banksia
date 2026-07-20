from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, case, exists, select, true, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError, stale_dispatch_error

if TYPE_CHECKING:
    from autoclaw.runtime.node_operations.contracts import NodeOperationScope


@dataclass(frozen=True)
class NodeOperationAuthority:
    task_id: str
    flow_id: str
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    node_key: str
    node_kind: NodeKind
    flow_revision_id: str
    work_plan_revision: int
    dispatch_status: str
    opened_reason: str
    predecessor_dispatch_id: str | None
    expected_provider_start_revision: int | None
    assignment: AssignmentModel
    attempt: AttemptModel
    flow_node: FlowNodeModel
    capabilities: DispatchCapabilitySetModel


@dataclass(frozen=True)
class NodeActivityRefresh:
    activity_revision: int
    occurred_at: datetime


async def read_node_operation_authority(
    session: AsyncSession,
    scope: NodeOperationScope,
) -> NodeOperationAuthority:
    dispatch, flow = await _read_current_dispatch_and_flow(session, scope)
    flow_revision_id = flow.active_flow_revision_id
    assert flow_revision_id is not None
    assignment, attempt = await _read_current_assignment_and_attempt(
        session,
        scope,
        dispatch=dispatch,
        flow=flow,
    )
    flow_node = await _read_current_flow_node(
        session,
        dispatch=dispatch,
        flow=flow,
        assignment=assignment,
    )
    capabilities = await _read_dispatch_capabilities(session, dispatch.dispatch_id)
    return NodeOperationAuthority(
        task_id=scope.task_id,
        flow_id=flow.flow_id,
        dispatch_id=dispatch.dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        node_key=dispatch.node_key,
        node_kind=NodeKind(flow_node.structural_kind),
        flow_revision_id=flow_revision_id,
        work_plan_revision=assignment.work_plan_revision,
        dispatch_status=dispatch.status,
        opened_reason=dispatch.opened_reason,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        expected_provider_start_revision=scope.provider_start_revision,
        assignment=assignment,
        attempt=attempt,
        flow_node=flow_node,
        capabilities=capabilities,
    )


async def refresh_node_activity(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    occurred_at: datetime,
) -> NodeActivityRefresh:
    result = await session.execute(
        update(DispatchTurnModel)
        .where(
            DispatchTurnModel.dispatch_id == authority.dispatch_id,
            DispatchTurnModel.task_id == authority.task_id,
            DispatchTurnModel.assignment_id == authority.assignment_id,
            DispatchTurnModel.attempt_id == authority.attempt_id,
            DispatchTurnModel.status.in_(("starting", "open")),
            exact_node_operation_authority_exists(authority),
        )
        .values(
            last_node_activity_at=case(
                (
                    DispatchTurnModel.last_node_activity_at.is_(None),
                    occurred_at,
                ),
                (
                    DispatchTurnModel.last_node_activity_at < occurred_at,
                    occurred_at,
                ),
                else_=DispatchTurnModel.last_node_activity_at,
            ),
            node_activity_revision=DispatchTurnModel.node_activity_revision + 1,
        )
        .returning(
            DispatchTurnModel.node_activity_revision,
            DispatchTurnModel.last_node_activity_at,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise stale_dispatch_error("dispatch lost currentness before Node activity admission")
    committed_at = row.last_node_activity_at
    assert committed_at is not None
    return NodeActivityRefresh(
        activity_revision=int(row.node_activity_revision),
        occurred_at=committed_at,
    )


async def claim_exact_node_operation_transition(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    """Establish the short exact-dispatch transaction boundary for a mutation."""
    try:
        claimed_dispatch_id = await session.scalar(
            update(DispatchTurnModel)
            .where(
                DispatchTurnModel.dispatch_id == authority.dispatch_id,
                DispatchTurnModel.task_id == authority.task_id,
                DispatchTurnModel.flow_id == authority.flow_id,
                DispatchTurnModel.assignment_id == authority.assignment_id,
                DispatchTurnModel.attempt_id == authority.attempt_id,
                DispatchTurnModel.node_key == authority.node_key,
                DispatchTurnModel.status.in_(("starting", "open")),
                exact_node_operation_authority_exists(authority),
            )
            .values(node_activity_revision=DispatchTurnModel.node_activity_revision)
            .returning(DispatchTurnModel.dispatch_id)
        )
    except DBAPIError as exc:
        if not _is_expected_transition_contention(exc):
            raise
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another Node operation won the exact dispatch transition",
            is_retryable=False,
        ) from exc
    if claimed_dispatch_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed exact dispatch authority",
            is_retryable=False,
        )


def exact_node_operation_authority_exists(
    authority: NodeOperationAuthority,
) -> ColumnElement[bool]:
    """Build the exact-current predicate for one operation-owned write."""
    return and_(
        exists(
            select(FlowModel.flow_id).where(
                FlowModel.flow_id == authority.flow_id,
                FlowModel.task_id == authority.task_id,
                FlowModel.status == "running",
                FlowModel.current_dispatch_id == authority.dispatch_id,
                FlowModel.active_flow_revision_id == authority.flow_revision_id,
            )
        ),
        exists(
            select(DispatchTurnModel.dispatch_id).where(
                DispatchTurnModel.dispatch_id == authority.dispatch_id,
                DispatchTurnModel.task_id == authority.task_id,
                DispatchTurnModel.flow_id == authority.flow_id,
                DispatchTurnModel.assignment_id == authority.assignment_id,
                DispatchTurnModel.attempt_id == authority.attempt_id,
                DispatchTurnModel.node_key == authority.node_key,
                DispatchTurnModel.status.in_(("starting", "open")),
                _managed_provider_start_revision_matches(authority),
            )
        ),
        exists(
            select(AssignmentModel.assignment_id).where(
                AssignmentModel.assignment_id == authority.assignment_id,
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.flow_id == authority.flow_id,
                AssignmentModel.flow_revision_id == authority.flow_revision_id,
                AssignmentModel.node_key == authority.node_key,
                AssignmentModel.current_attempt_id == authority.attempt_id,
            )
        ),
        exists(
            select(AttemptModel.attempt_id).where(
                AttemptModel.attempt_id == authority.attempt_id,
                AttemptModel.assignment_id == authority.assignment_id,
                AttemptModel.task_id == authority.task_id,
                AttemptModel.flow_id == authority.flow_id,
                AttemptModel.node_key == authority.node_key,
                AttemptModel.status.in_(("pending", "running")),
            )
        ),
        exists(
            select(FlowNodeModel.flow_node_id).where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.flow_node_id == authority.flow_node.flow_node_id,
                FlowNodeModel.node_key == authority.node_key,
                FlowNodeModel.current_assignment_id == authority.assignment_id,
            )
        ),
    )


async def _read_current_dispatch_and_flow(
    session: AsyncSession,
    scope: NodeOperationScope,
) -> tuple[DispatchTurnModel, FlowModel]:
    dispatch = await session.get(
        DispatchTurnModel,
        scope.dispatch_id,
        populate_existing=True,
    )
    if dispatch is None or dispatch.task_id != scope.task_id:
        raise RuntimeOperationError(
            code=OperationFailureCode.SCOPE_MISMATCH,
            summary="task_id and dispatch_id do not identify one dispatch",
            is_retryable=False,
        )
    if (
        scope.provider_start_revision is not None
        and dispatch.provider_start_revision != scope.provider_start_revision
    ):
        raise stale_dispatch_error("managed binding provider-start generation is no longer current")
    if dispatch.status not in {"starting", "open"}:
        raise stale_dispatch_error("dispatch is no longer current Node authority")

    flow = await session.get(
        FlowModel,
        dispatch.flow_id,
        populate_existing=True,
    )
    if (
        flow is None
        or flow.task_id != scope.task_id
        or flow.status != "running"
        or flow.current_dispatch_id != dispatch.dispatch_id
        or flow.active_flow_revision_id is None
    ):
        raise stale_dispatch_error("dispatch is no longer exact current flow authority")
    return dispatch, flow


async def _read_current_assignment_and_attempt(
    session: AsyncSession,
    scope: NodeOperationScope,
    *,
    dispatch: DispatchTurnModel,
    flow: FlowModel,
) -> tuple[AssignmentModel, AttemptModel]:
    assignment = await session.get(
        AssignmentModel,
        dispatch.assignment_id,
        populate_existing=True,
    )
    attempt = await session.get(
        AttemptModel,
        dispatch.attempt_id,
        populate_existing=True,
    )
    if (
        assignment is None
        or attempt is None
        or assignment.task_id != scope.task_id
        or assignment.flow_id != flow.flow_id
        or assignment.flow_revision_id != flow.active_flow_revision_id
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.node_key != dispatch.node_key
        or attempt.assignment_id != assignment.assignment_id
        or attempt.task_id != scope.task_id
        or attempt.flow_id != flow.flow_id
        or attempt.node_key != dispatch.node_key
        or attempt.status not in {"pending", "running"}
    ):
        raise stale_dispatch_error("dispatch assignment or attempt is no longer current")
    return assignment, attempt


async def _read_current_flow_node(
    session: AsyncSession,
    *,
    dispatch: DispatchTurnModel,
    flow: FlowModel,
    assignment: AssignmentModel,
) -> FlowNodeModel:
    flow_node = await session.scalar(
        select(FlowNodeModel)
        .where(
            FlowNodeModel.flow_revision_id == flow.active_flow_revision_id,
            FlowNodeModel.node_key == dispatch.node_key,
        )
        .execution_options(populate_existing=True)
    )
    if (
        flow_node is None
        or flow_node.flow_id != flow.flow_id
        or flow_node.flow_node_id != assignment.flow_node_id
        or flow_node.current_assignment_id != assignment.assignment_id
    ):
        raise stale_dispatch_error("dispatch node is no longer current")
    return flow_node


async def _read_dispatch_capabilities(
    session: AsyncSession,
    dispatch_id: str,
) -> DispatchCapabilitySetModel:
    capabilities = await session.get(
        DispatchCapabilitySetModel,
        dispatch_id,
        populate_existing=True,
    )
    if capabilities is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_STATE,
            summary="current dispatch is missing its frozen capability set",
            is_retryable=False,
        )
    return capabilities


def _managed_provider_start_revision_matches(
    authority: NodeOperationAuthority,
) -> ColumnElement[bool]:
    expected_revision = authority.expected_provider_start_revision
    if expected_revision is None:
        return true()
    return DispatchTurnModel.provider_start_revision == expected_revision


def _is_expected_transition_contention(exc: DBAPIError) -> bool:
    original = exc.orig
    if isinstance(original, sqlite3.OperationalError):
        sqlite_error_code = getattr(original, "sqlite_errorcode", None)
        return sqlite_error_code in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_BUSY_SNAPSHOT,
            sqlite3.SQLITE_LOCKED,
            sqlite3.SQLITE_LOCKED_SHAREDCACHE,
        }
    driver_cause = getattr(original, "__cause__", None)
    sqlstate = (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or getattr(driver_cause, "sqlstate", None)
    )
    return sqlstate in {"40001", "55P03"}


__all__ = [
    "NodeActivityRefresh",
    "NodeOperationAuthority",
    "claim_exact_node_operation_transition",
    "exact_node_operation_authority_exists",
    "read_node_operation_authority",
    "refresh_node_activity",
]

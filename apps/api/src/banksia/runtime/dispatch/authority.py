from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Never

from sqlalchemy import and_, case, exists, select, true, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
)
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.currentness import (
    AttemptDispatchIdentity,
    attempt_dispatch_is_current,
)
from banksia.runtime.errors import RuntimeOperationError, stale_dispatch_error
from banksia.runtime.team.currentness import current_team_selects_member

if TYPE_CHECKING:
    from banksia.runtime.node_operations.contracts import NodeOperationScope


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
    flow_control_revision: int
    work_plan_revision: int
    dispatch_status: str
    opened_reason: str
    predecessor_dispatch_id: str | None
    expected_provider_start_revision: int | None
    dispatch: DispatchTurnModel
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
    flow_revision_id = dispatch.flow_revision_id
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
        flow_control_revision=flow.control_revision,
        work_plan_revision=assignment.work_plan_revision,
        dispatch_status=dispatch.status,
        opened_reason=dispatch.opened_reason,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        expected_provider_start_revision=scope.provider_start_revision,
        dispatch=dispatch,
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
    await claim_exact_node_operation_flow(session, authority)
    try:
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
    except DBAPIError as exc:
        _raise_expected_transition_contention(exc)
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
    await claim_exact_node_operation_flow(session, authority)
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
                DispatchTurnModel.flow_revision_id == authority.flow_revision_id,
                DispatchTurnModel.flow_node_id == authority.flow_node.flow_node_id,
                DispatchTurnModel.team_revision_id == authority.dispatch.team_revision_id,
                DispatchTurnModel.member_id == authority.assignment.member_id,
                DispatchTurnModel.member_configuration_id
                == authority.dispatch.member_configuration_id,
                DispatchTurnModel.member_branch_basis_id
                == authority.dispatch.member_branch_basis_id,
                DispatchTurnModel.status.in_(("starting", "open")),
                exact_node_operation_authority_exists(authority),
            )
            .values(node_activity_revision=DispatchTurnModel.node_activity_revision)
            .returning(DispatchTurnModel.dispatch_id)
        )
    except DBAPIError as exc:
        _raise_expected_transition_contention(exc)
    if claimed_dispatch_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed exact dispatch authority",
            is_retryable=False,
        )


async def claim_exact_node_operation_flow(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    """Lock and validate the exact running Flow before any Node-owned row."""

    try:
        claimed_flow_id = await session.scalar(
            update(FlowModel)
            .where(
                FlowModel.flow_id == authority.flow_id,
                FlowModel.task_id == authority.task_id,
                FlowModel.status == "running",
                FlowModel.control_revision == authority.flow_control_revision,
                exact_node_operation_authority_exists(authority),
            )
            .values(control_revision=FlowModel.control_revision)
            .returning(FlowModel.flow_id)
        )
    except DBAPIError as exc:
        _raise_expected_transition_contention(exc)
    if claimed_flow_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed exact Flow authority",
            is_retryable=False,
        )


def exact_node_operation_authority_exists(
    authority: NodeOperationAuthority,
) -> ColumnElement[bool]:
    """Build the exact-current predicate for one operation-owned write."""
    return and_(
        attempt_dispatch_is_current(
            AttemptDispatchIdentity(
                task_id=authority.task_id,
                flow_id=authority.flow_id,
                assignment_id=authority.assignment_id,
                attempt_id=authority.attempt_id,
                dispatch_id=authority.dispatch_id,
            )
        ),
        exists(
            select(FlowModel.flow_id).where(
                FlowModel.flow_id == authority.flow_id,
                FlowModel.task_id == authority.task_id,
                FlowModel.status == "running",
                FlowModel.control_revision == authority.flow_control_revision,
            )
        ),
        current_team_selects_member(
            task_id=authority.task_id,
            member_id=authority.dispatch.member_id,
            member_configuration_id=authority.dispatch.member_configuration_id,
            member_branch_basis_id=authority.dispatch.member_branch_basis_id,
        ),
        exists(
            select(DispatchTurnModel.dispatch_id).where(
                DispatchTurnModel.dispatch_id == authority.dispatch_id,
                DispatchTurnModel.task_id == authority.task_id,
                DispatchTurnModel.flow_id == authority.flow_id,
                DispatchTurnModel.assignment_id == authority.assignment_id,
                DispatchTurnModel.attempt_id == authority.attempt_id,
                DispatchTurnModel.node_key == authority.node_key,
                DispatchTurnModel.flow_revision_id == authority.flow_revision_id,
                DispatchTurnModel.status.in_(("starting", "open")),
                _managed_provider_start_revision_matches(authority),
            )
        ),
        exists(
            select(AssignmentModel.assignment_id).where(
                AssignmentModel.assignment_id == authority.assignment_id,
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.flow_id == authority.flow_id,
                AssignmentModel.member_id == authority.dispatch.member_id,
                AssignmentModel.node_key == authority.node_key,
                AssignmentModel.current_attempt_id == authority.attempt_id,
                AssignmentModel.closed_at.is_(None),
                AssignmentModel.superseded_at.is_(None),
            )
        ),
        exists(
            select(FlowNodeModel.flow_node_id).where(
                FlowNodeModel.flow_id == authority.flow_id,
                FlowNodeModel.flow_revision_id == authority.flow_revision_id,
                FlowNodeModel.flow_node_id == authority.flow_node.flow_node_id,
                FlowNodeModel.node_key == authority.node_key,
                FlowNodeModel.team_revision_id == authority.dispatch.team_revision_id,
                FlowNodeModel.member_id == authority.dispatch.member_id,
                FlowNodeModel.member_configuration_id == authority.dispatch.member_configuration_id,
                FlowNodeModel.member_branch_basis_id == authority.dispatch.member_branch_basis_id,
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
    if flow is None or flow.task_id != scope.task_id or flow.status != "running":
        raise stale_dispatch_error("dispatch is no longer in the running Flow")
    task_team_retains_selection = await session.scalar(
        select(
            current_team_selects_member(
                task_id=scope.task_id,
                member_id=dispatch.member_id,
                member_configuration_id=dispatch.member_configuration_id,
                member_branch_basis_id=dispatch.member_branch_basis_id,
            )
        )
    )
    if not task_team_retains_selection:
        raise stale_dispatch_error("current Team no longer retains the Dispatch selection")
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
        or assignment.member_id != dispatch.member_id
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.closed_at is not None
        or assignment.superseded_at is not None
        or assignment.node_key != dispatch.node_key
        or attempt.assignment_id != assignment.assignment_id
        or attempt.task_id != scope.task_id
        or attempt.flow_id != flow.flow_id
        or attempt.node_key != dispatch.node_key
        or attempt.status != "running"
        or attempt.current_dispatch_id != dispatch.dispatch_id
        or attempt.current_wait_id is not None
    ):
        raise stale_dispatch_error("dispatch assignment or Attempt lane is no longer current")
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
        .where(FlowNodeModel.flow_node_id == dispatch.flow_node_id)
        .execution_options(populate_existing=True)
    )
    if (
        flow_node is None
        or flow_node.flow_id != flow.flow_id
        or flow_node.flow_revision_id != dispatch.flow_revision_id
        or flow_node.node_key != dispatch.node_key
        or flow_node.team_revision_id != dispatch.team_revision_id
        or flow_node.member_id != dispatch.member_id
        or flow_node.member_configuration_id != dispatch.member_configuration_id
        or flow_node.member_branch_basis_id != dispatch.member_branch_basis_id
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
    return sqlstate in {"40001", "40P01", "55P03"}


def _raise_expected_transition_contention(exc: DBAPIError) -> Never:
    if not _is_expected_transition_contention(exc):
        raise exc
    raise RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary="another Node operation won the exact Flow transition",
        is_retryable=False,
    ) from exc


__all__ = [
    "NodeActivityRefresh",
    "NodeOperationAuthority",
    "claim_exact_node_operation_flow",
    "claim_exact_node_operation_transition",
    "exact_node_operation_authority_exists",
    "read_node_operation_authority",
    "refresh_node_activity",
]

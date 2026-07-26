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
    TaskModel,
    TeamRevisionMemberModel,
)
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
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    member_id: str
    is_task_lead: bool
    has_direct_team: bool
    team_revision_id: str
    current_team_revision_id: str
    task_control_revision: int
    work_plan_revision: int
    dispatch_status: str
    opened_reason: str
    predecessor_dispatch_id: str | None
    expected_provider_start_revision: int | None
    dispatch: DispatchTurnModel
    assignment: AssignmentModel
    attempt: AttemptModel
    team_selection: TeamRevisionMemberModel
    capabilities: DispatchCapabilitySetModel


@dataclass(frozen=True)
class NodeActivityRefresh:
    activity_revision: int
    occurred_at: datetime


async def read_node_operation_authority(
    session: AsyncSession,
    scope: NodeOperationScope,
) -> NodeOperationAuthority:
    dispatch, task = await _read_current_dispatch_and_task(session, scope)
    assignment, attempt = await _read_current_assignment_and_attempt(
        session,
        scope,
        dispatch=dispatch,
    )
    selection = await _read_current_team_selection(session, dispatch=dispatch)
    current_team_revision_id = task.current_team_revision_id
    if current_team_revision_id is None:
        raise stale_dispatch_error("running Task has no current Team revision")
    has_direct_team = bool(
        await session.scalar(
            select(
                exists().where(
                    TeamRevisionMemberModel.task_id == task.task_id,
                    TeamRevisionMemberModel.team_revision_id == current_team_revision_id,
                    TeamRevisionMemberModel.parent_member_id == dispatch.member_id,
                )
            )
        )
    )
    capabilities = await _read_dispatch_capabilities(session, dispatch.dispatch_id)
    return NodeOperationAuthority(
        task_id=scope.task_id,
        dispatch_id=dispatch.dispatch_id,
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        member_id=dispatch.member_id,
        is_task_lead=task.root_assignment_id == assignment.assignment_id,
        has_direct_team=has_direct_team,
        team_revision_id=dispatch.team_revision_id,
        current_team_revision_id=current_team_revision_id,
        task_control_revision=task.control_revision,
        work_plan_revision=assignment.work_plan_revision,
        dispatch_status=dispatch.status,
        opened_reason=dispatch.opened_reason,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        expected_provider_start_revision=scope.provider_start_revision,
        dispatch=dispatch,
        assignment=assignment,
        attempt=attempt,
        team_selection=selection,
        capabilities=capabilities,
    )


async def refresh_node_activity(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    occurred_at: datetime,
) -> NodeActivityRefresh:
    await claim_exact_node_operation_task(session, authority)
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
                    (DispatchTurnModel.last_node_activity_at.is_(None), occurred_at),
                    (DispatchTurnModel.last_node_activity_at < occurred_at, occurred_at),
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
        raise stale_dispatch_error("Dispatch lost currentness before Member activity admission")
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
    """Establish the short exact-Dispatch transaction boundary for a mutation."""

    await claim_exact_node_operation_task(session, authority)
    try:
        claimed_dispatch_id = await session.scalar(
            update(DispatchTurnModel)
            .where(
                DispatchTurnModel.dispatch_id == authority.dispatch_id,
                DispatchTurnModel.task_id == authority.task_id,
                DispatchTurnModel.assignment_id == authority.assignment_id,
                DispatchTurnModel.attempt_id == authority.attempt_id,
                DispatchTurnModel.team_revision_id == authority.team_revision_id,
                DispatchTurnModel.member_id == authority.member_id,
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
            summary="another transition changed exact Dispatch authority",
            is_retryable=False,
        )


async def claim_exact_node_operation_task(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> None:
    """Lock and validate the exact running Task before any Member-owned row."""

    try:
        claimed_task_id = await session.scalar(
            update(TaskModel)
            .where(
                TaskModel.task_id == authority.task_id,
                TaskModel.status == "running",
                TaskModel.control_revision == authority.task_control_revision,
                exact_node_operation_authority_exists(authority),
            )
            .values(updated_at=TaskModel.updated_at)
            .returning(TaskModel.task_id)
        )
    except DBAPIError as exc:
        _raise_expected_transition_contention(exc)
    if claimed_task_id is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another transition changed exact Task authority",
            is_retryable=False,
        )


def exact_node_operation_authority_exists(
    authority: NodeOperationAuthority,
) -> ColumnElement[bool]:
    return and_(
        attempt_dispatch_is_current(
            AttemptDispatchIdentity(
                task_id=authority.task_id,
                assignment_id=authority.assignment_id,
                attempt_id=authority.attempt_id,
                dispatch_id=authority.dispatch_id,
            )
        ),
        exists(
            select(TaskModel.task_id).where(
                TaskModel.task_id == authority.task_id,
                TaskModel.status == "running",
                TaskModel.control_revision == authority.task_control_revision,
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
                DispatchTurnModel.assignment_id == authority.assignment_id,
                DispatchTurnModel.attempt_id == authority.attempt_id,
                DispatchTurnModel.team_revision_id == authority.team_revision_id,
                DispatchTurnModel.member_id == authority.member_id,
                DispatchTurnModel.status.in_(("starting", "open")),
                _managed_provider_start_revision_matches(authority),
            )
        ),
        exists(
            select(AssignmentModel.assignment_id).where(
                AssignmentModel.assignment_id == authority.assignment_id,
                AssignmentModel.task_id == authority.task_id,
                AssignmentModel.member_id == authority.member_id,
                AssignmentModel.current_attempt_id == authority.attempt_id,
                AssignmentModel.closed_at.is_(None),
            )
        ),
        exists(
            select(TeamRevisionMemberModel.member_id).where(
                TeamRevisionMemberModel.task_id == authority.task_id,
                TeamRevisionMemberModel.team_revision_id == authority.team_revision_id,
                TeamRevisionMemberModel.member_id == authority.member_id,
                TeamRevisionMemberModel.member_configuration_id
                == authority.dispatch.member_configuration_id,
                TeamRevisionMemberModel.member_branch_basis_id
                == authority.dispatch.member_branch_basis_id,
            )
        ),
    )


async def _read_current_dispatch_and_task(
    session: AsyncSession,
    scope: NodeOperationScope,
) -> tuple[DispatchTurnModel, TaskModel]:
    dispatch = await session.get(DispatchTurnModel, scope.dispatch_id, populate_existing=True)
    if dispatch is None or dispatch.task_id != scope.task_id:
        raise RuntimeOperationError(
            code=OperationFailureCode.SCOPE_MISMATCH,
            summary="task_id and dispatch_id do not identify one Dispatch",
            is_retryable=False,
        )
    if (
        scope.provider_start_revision is not None
        and dispatch.provider_start_revision != scope.provider_start_revision
    ):
        raise stale_dispatch_error("managed binding provider-start generation is no longer current")
    if dispatch.status not in {"starting", "open"}:
        raise stale_dispatch_error("Dispatch is no longer current Member authority")
    task = await session.get(TaskModel, dispatch.task_id, populate_existing=True)
    if task is None or task.status != "running":
        raise stale_dispatch_error("Dispatch is no longer in a running Task")
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
    return dispatch, task


async def _read_current_assignment_and_attempt(
    session: AsyncSession,
    scope: NodeOperationScope,
    *,
    dispatch: DispatchTurnModel,
) -> tuple[AssignmentModel, AttemptModel]:
    assignment = await session.get(AssignmentModel, dispatch.assignment_id, populate_existing=True)
    attempt = await session.get(AttemptModel, dispatch.attempt_id, populate_existing=True)
    if (
        assignment is None
        or attempt is None
        or assignment.task_id != scope.task_id
        or assignment.member_id != dispatch.member_id
        or assignment.current_attempt_id != attempt.attempt_id
        or assignment.closed_at is not None
        or attempt.assignment_id != assignment.assignment_id
        or attempt.task_id != scope.task_id
        or attempt.status != "running"
        or attempt.current_dispatch_id != dispatch.dispatch_id
        or attempt.current_wait_id is not None
    ):
        raise stale_dispatch_error("Dispatch Assignment or Attempt lane is no longer current")
    return assignment, attempt


async def _read_current_team_selection(
    session: AsyncSession,
    *,
    dispatch: DispatchTurnModel,
) -> TeamRevisionMemberModel:
    selection = await session.scalar(
        select(TeamRevisionMemberModel)
        .where(
            TeamRevisionMemberModel.task_id == dispatch.task_id,
            TeamRevisionMemberModel.team_revision_id == dispatch.team_revision_id,
            TeamRevisionMemberModel.member_id == dispatch.member_id,
            TeamRevisionMemberModel.member_configuration_id == dispatch.member_configuration_id,
            TeamRevisionMemberModel.member_branch_basis_id == dispatch.member_branch_basis_id,
        )
        .execution_options(populate_existing=True)
    )
    if selection is None:
        raise stale_dispatch_error("Dispatch Team selection is no longer current")
    return selection


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
            summary="current Dispatch is missing its frozen capability set",
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
        summary="another Member operation won the exact Task transition",
        is_retryable=False,
    ) from exc


__all__ = [
    "NodeActivityRefresh",
    "NodeOperationAuthority",
    "claim_exact_node_operation_task",
    "claim_exact_node_operation_transition",
    "exact_node_operation_authority_exists",
    "read_node_operation_authority",
    "refresh_node_activity",
]

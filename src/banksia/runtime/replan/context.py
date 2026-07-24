from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.replan.planning import PlannedMember, ReplanMutation
from banksia.runtime.team.currentness import current_team_selects_member


@dataclass(frozen=True, slots=True)
class ReplanCommitContext:
    """Exact current Task and Team snapshot read before the replan CAS."""

    task: TaskModel
    team_revision: TeamRevisionModel
    members: dict[str, PlannedMember]


async def read_replan_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> ReplanCommitContext:
    """Read the complete current Team selected by the exact running Task."""

    task = await session.get(TaskModel, authority.task_id)
    selection_is_current = await session.scalar(
        select(
            current_team_selects_member(
                task_id=authority.task_id,
                member_id=authority.member_id,
                member_configuration_id=authority.dispatch.member_configuration_id,
                member_branch_basis_id=authority.dispatch.member_branch_basis_id,
            )
        )
    )
    if (
        task is None
        or task.status != "running"
        or task.control_revision != authority.task_control_revision
        or task.current_team_revision_id is None
        or not selection_is_current
    ):
        raise _conflict("current Task or Team changed before replan admission")
    team_revision = await session.get(TeamRevisionModel, task.current_team_revision_id)
    if team_revision is None or team_revision.task_id != authority.task_id:
        raise _conflict("current Team revision is missing")
    members = await _read_planned_members(
        session,
        task_id=task.task_id,
        team_revision_id=team_revision.team_revision_id,
    )
    return ReplanCommitContext(task, team_revision, members)


async def require_replan_admission(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    mutation: ReplanMutation,
) -> None:
    """Reject a replan that conflicts with a current wait or affected active work."""

    caller_wait = await session.scalar(
        select(
            exists().where(
                AttemptModel.attempt_id == authority.attempt_id,
                AttemptModel.task_id == authority.task_id,
                AttemptModel.assignment_id == authority.assignment_id,
                AttemptModel.current_wait_id.is_not(None),
            )
        )
    )
    if caller_wait:
        raise _illegal_state("replan requires no current caller wait")
    if not mutation.affected_existing_ids:
        return
    busy_statement = (
        select(1)
        .select_from(AssignmentModel)
        .join(
            AttemptModel,
            (AttemptModel.task_id == AssignmentModel.task_id)
            & (AttemptModel.assignment_id == AssignmentModel.assignment_id)
            & (AttemptModel.attempt_id == AssignmentModel.current_attempt_id),
        )
        .where(
            AssignmentModel.task_id == authority.task_id,
            AssignmentModel.member_id.in_(mutation.affected_existing_ids),
            AssignmentModel.assignment_id != authority.assignment_id,
            AssignmentModel.superseded_at.is_(None),
            AttemptModel.status.in_(("pending", "running")),
        )
    )
    if await session.scalar(select(exists(busy_statement))):
        raise _illegal_state("replan target contains a Member with active assigned work")


async def _read_planned_members(
    session: AsyncSession,
    *,
    task_id: str,
    team_revision_id: str,
) -> dict[str, PlannedMember]:
    rows = (
        await session.execute(
            select(TeamRevisionMemberModel, MemberConfigurationModel)
            .options(raiseload("*"))
            .join(
                MemberConfigurationModel,
                (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id)
                & (
                    MemberConfigurationModel.member_configuration_id
                    == TeamRevisionMemberModel.member_configuration_id
                ),
            )
            .where(
                TeamRevisionMemberModel.task_id == task_id,
                TeamRevisionMemberModel.team_revision_id == team_revision_id,
            )
            .order_by(TeamRevisionMemberModel.preorder_index)
        )
    ).all()
    members = {
        selection.member_id: _planned_member(selection, configuration)
        for selection, configuration in rows
    }
    for member in members.values():
        if member.parent_member_id is not None:
            if member.parent_member_id not in members:
                raise _conflict("current Team selection contains a missing parent")
            members[member.parent_member_id].children.append(member.member_id)
    selection_count = await session.scalar(
        select(func.count())
        .select_from(TeamRevisionMemberModel)
        .where(
            TeamRevisionMemberModel.task_id == task_id,
            TeamRevisionMemberModel.team_revision_id == team_revision_id,
        )
    )
    if len(rows) != selection_count or len(rows) != len(members):
        raise _conflict("current Team selection is incomplete")
    return members


def _planned_member(
    selection: TeamRevisionMemberModel,
    configuration: MemberConfigurationModel,
) -> PlannedMember:
    return PlannedMember(
        member_id=selection.member_id,
        parent_member_id=selection.parent_member_id,
        title=configuration.title,
        description=configuration.description,
        instruction=configuration.instruction,
        provider_json=configuration.requested_provider_json,
        capabilities_json=configuration.requested_capabilities_json,
        configuration_id=selection.member_configuration_id,
        branch_basis_id=selection.member_branch_basis_id,
        source_selection=selection,
        source_configuration=configuration,
    )


def _conflict(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary=summary,
        is_retryable=False,
    )


def _illegal_state(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary=summary,
        is_retryable=False,
    )


__all__ = [
    "ReplanCommitContext",
    "read_replan_context",
    "require_replan_admission",
]

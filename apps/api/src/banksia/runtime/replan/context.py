from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from banksia.persistence.models import (
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    FlowWaitModel,
    HumanRequestModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.persistence.models.runtime.common import COMMAND_RUN_TERMINAL_STATE_VALUES
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.replan.planning import PlannedMember, ReplanMutation


@dataclass(frozen=True, slots=True)
class ReplanCommitContext:
    """Exact current Team and Flow substrate read before one replan CAS."""

    task: TaskModel
    flow: FlowModel
    team_revision: TeamRevisionModel
    flow_revision: FlowRevisionModel
    members: dict[str, PlannedMember]


async def read_replan_context(
    session: AsyncSession,
    authority: NodeOperationAuthority,
) -> ReplanCommitContext:
    """Read one complete current Team and its matching Flow projection."""

    task = await session.get(TaskModel, authority.task_id)
    flow = await session.get(FlowModel, authority.flow_id)
    if (
        task is None
        or flow is None
        or task.current_team_revision_id != authority.dispatch.team_revision_id
        or flow.active_flow_revision_id != authority.flow_revision_id
    ):
        raise _conflict("current Team or Flow changed before replan admission")
    team_revision = await session.get(TeamRevisionModel, task.current_team_revision_id)
    flow_revision = await session.get(FlowRevisionModel, flow.active_flow_revision_id)
    if team_revision is None or flow_revision is None:
        raise _conflict("current Team or Flow revision is missing")
    members = await _read_planned_members(
        session,
        task_id=task.task_id,
        team_revision_id=team_revision.team_revision_id,
        flow_id=flow.flow_id,
        flow_revision_id=flow_revision.flow_revision_id,
    )
    return ReplanCommitContext(task, flow, team_revision, flow_revision, members)


async def require_replan_admission(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    mutation: ReplanMutation,
) -> None:
    """Reject a replan that conflicts with staged transfer or affected active work."""

    staged_decision = await session.scalar(
        select(exists().where(AssignmentDecisionModel.source_dispatch_id == authority.dispatch_id))
    )
    external_wait = await session.scalar(
        select(
            exists().where(FlowWaitModel.flow_id == authority.flow_id)
            | exists().where(
                HumanRequestModel.flow_id == authority.flow_id,
                HumanRequestModel.status == "open",
            )
            | exists().where(
                CommandRunModel.flow_id == authority.flow_id,
                CommandRunModel.state.not_in(COMMAND_RUN_TERMINAL_STATE_VALUES),
            )
        )
    )
    if staged_decision or external_wait:
        raise _illegal_state("replan requires no staged handoff or unresolved external wait")
    if not mutation.affected_existing_ids:
        return
    busy_statement = (
        select(1)
        .select_from(AssignmentModel)
        .join(
            AttemptModel,
            (AttemptModel.assignment_id == AssignmentModel.assignment_id)
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
    flow_id: str,
    flow_revision_id: str,
) -> dict[str, PlannedMember]:
    rows = (
        await session.execute(
            select(TeamRevisionMemberModel, MemberConfigurationModel, FlowNodeModel)
            .options(raiseload("*"))
            .join(
                MemberConfigurationModel,
                (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                & (
                    MemberConfigurationModel.member_configuration_id
                    == TeamRevisionMemberModel.member_configuration_id
                ),
            )
            .join(
                FlowNodeModel,
                (FlowNodeModel.task_id == TeamRevisionMemberModel.task_id)
                & (FlowNodeModel.team_revision_id == TeamRevisionMemberModel.team_revision_id)
                & (FlowNodeModel.member_id == TeamRevisionMemberModel.member_id)
                & (FlowNodeModel.flow_id == flow_id)
                & (FlowNodeModel.flow_revision_id == flow_revision_id),
            )
            .where(
                TeamRevisionMemberModel.task_id == task_id,
                TeamRevisionMemberModel.team_revision_id == team_revision_id,
            )
            .order_by(TeamRevisionMemberModel.preorder_index)
        )
    ).all()
    members = {
        selection.member_id: _planned_member(selection, configuration, node)
        for selection, configuration, node in rows
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
        raise _conflict("current Team and Flow are not a complete one-to-one projection")
    return members


def _planned_member(
    selection: TeamRevisionMemberModel,
    configuration: MemberConfigurationModel,
    node: FlowNodeModel,
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
        source_node=node,
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

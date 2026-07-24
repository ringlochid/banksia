from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    DispatchTurnModel,
    HumanRequestModel,
    TaskModel,
    TeamRevisionMemberModel,
    WorkspaceBindingModel,
)
from banksia.runtime.watchdog.context import WatchdogRecoverySnapshot


def watchdog_context_is_current(
    snapshot: WatchdogRecoverySnapshot,
) -> ColumnElement[bool]:
    dispatch = snapshot.dispatch
    prompt = dispatch.prompt
    source_dispatch_id = prompt.predecessor_dispatch_id
    return (
        exists().where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.task_root_path == dispatch.task_root_path,
            TaskModel.status == "running",
            TaskModel.current_team_revision_id == prompt.team_revision_id,
            TaskModel.control_revision == dispatch.task_control_revision,
        )
        & exists().where(
            TeamRevisionMemberModel.task_id == prompt.task_id,
            TeamRevisionMemberModel.team_revision_id == prompt.team_revision_id,
            TeamRevisionMemberModel.member_id == prompt.member_id,
            TeamRevisionMemberModel.member_configuration_id == prompt.member_configuration_id,
            TeamRevisionMemberModel.member_branch_basis_id == prompt.member_branch_basis_id,
        )
        & exists().where(
            AssignmentModel.assignment_id == prompt.assignment_id,
            AssignmentModel.task_id == prompt.task_id,
            AssignmentModel.member_id == prompt.member_id,
            AssignmentModel.current_attempt_id == prompt.attempt_id,
            AssignmentModel.work_plan_revision == dispatch.assignment_work_plan_revision,
            AssignmentModel.terminal_outcome.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
        & exists().where(
            AttemptModel.attempt_id == prompt.attempt_id,
            AttemptModel.assignment_id == prompt.assignment_id,
            AttemptModel.task_id == prompt.task_id,
            AttemptModel.status == "running",
            AttemptModel.current_dispatch_id == source_dispatch_id,
            AttemptModel.current_wait_id.is_(None),
        )
        & exists().where(
            DispatchTurnModel.dispatch_id == source_dispatch_id,
            DispatchTurnModel.task_id == prompt.task_id,
            DispatchTurnModel.assignment_id == prompt.assignment_id,
            DispatchTurnModel.attempt_id == prompt.attempt_id,
            DispatchTurnModel.team_revision_id == snapshot.source_team_revision_id,
            DispatchTurnModel.member_id == prompt.member_id,
            DispatchTurnModel.member_configuration_id == prompt.member_configuration_id,
            DispatchTurnModel.member_branch_basis_id == prompt.member_branch_basis_id,
            DispatchTurnModel.status == "open",
        )
        & exists().where(
            WorkspaceBindingModel.task_id == prompt.task_id,
            WorkspaceBindingModel.normalized_root_path == dispatch.workspace_root_path,
        )
    )


def watchdog_replacement_count_matches(
    snapshot: WatchdogRecoverySnapshot,
) -> ColumnElement[bool]:
    prompt = snapshot.dispatch.prompt
    lineage = aliased(DispatchTurnModel, name="watchdog_recovery_lineage")
    count = (
        select(func.count())
        .select_from(lineage)
        .where(
            lineage.task_id == prompt.task_id,
            lineage.assignment_id == prompt.assignment_id,
            lineage.attempt_id == prompt.attempt_id,
            lineage.opened_reason == "watchdog_recovery",
        )
        .scalar_subquery()
    )
    return count == snapshot.same_attempt_replacement_count


def dispatch_has_no_external_source(dispatch_id: str) -> ColumnElement[bool]:
    return ~exists().where(HumanRequestModel.source_dispatch_id == dispatch_id) & ~exists().where(
        CommandRunModel.source_dispatch_id == dispatch_id
    )


def dispatch_has_no_successor(dispatch_id: str) -> ColumnElement[bool]:
    successor = aliased(DispatchTurnModel, name="watchdog_successor")
    return ~exists().where(successor.predecessor_dispatch_id == dispatch_id)


def nullable_datetime_matches(
    column: InstrumentedAttribute[datetime | None],
    value: datetime | None,
) -> ColumnElement[bool]:
    return column.is_(None) if value is None else column == value


__all__ = [
    "dispatch_has_no_external_source",
    "dispatch_has_no_successor",
    "nullable_datetime_matches",
    "watchdog_context_is_current",
    "watchdog_replacement_count_matches",
]

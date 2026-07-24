"""Current Team-selection predicates for Attempt-local runtime authority."""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from banksia.persistence.models import (
    DispatchTurnModel,
    TaskModel,
    TeamRevisionMemberModel,
)

type SelectionValue = str | InstrumentedAttribute[str]


def dispatch_team_selection_is_current() -> ColumnElement[bool]:
    """Return the exact-current Team predicate correlated to a Dispatch row."""

    return current_team_selects_member(
        task_id=DispatchTurnModel.task_id,
        member_id=DispatchTurnModel.member_id,
        member_configuration_id=DispatchTurnModel.member_configuration_id,
        member_branch_basis_id=DispatchTurnModel.member_branch_basis_id,
    )


def current_team_selects_member(
    *,
    task_id: SelectionValue,
    member_id: SelectionValue,
    member_configuration_id: SelectionValue,
    member_branch_basis_id: SelectionValue,
) -> ColumnElement[bool]:
    """Return whether the current Team retains one exact member selection."""

    return exists(
        select(TeamRevisionMemberModel.member_id)
        .select_from(TaskModel)
        .join(
            TeamRevisionMemberModel,
            (TeamRevisionMemberModel.task_id == TaskModel.task_id)
            & (TeamRevisionMemberModel.team_revision_id == TaskModel.current_team_revision_id),
        )
        .where(
            TaskModel.task_id == task_id,
            TeamRevisionMemberModel.member_id == member_id,
            TeamRevisionMemberModel.member_configuration_id == member_configuration_id,
            TeamRevisionMemberModel.member_branch_basis_id == member_branch_basis_id,
        )
    )


__all__ = [
    "current_team_selects_member",
    "dispatch_team_selection_is_current",
]

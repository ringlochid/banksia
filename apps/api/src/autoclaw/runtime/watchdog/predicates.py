from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql.elements import ColumnElement

from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptModel,
    CommandRunModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    HumanRequestModel,
    NodePlanRevisionModel,
    TaskModel,
    WorkspaceBindingModel,
)
from autoclaw.runtime.watchdog.context import WatchdogRecoverySnapshot


def watchdog_context_is_current(
    snapshot: WatchdogRecoverySnapshot,
) -> ColumnElement[bool]:
    dispatch = snapshot.dispatch
    prompt = dispatch.prompt
    source_dispatch_id = prompt.predecessor_dispatch_id
    return (
        exists().where(
            FlowModel.flow_id == prompt.flow_id,
            FlowModel.task_id == prompt.task_id,
            FlowModel.compiled_plan_id == dispatch.compiled_plan_id,
            FlowModel.status == "running",
            FlowModel.active_flow_revision_id == prompt.flow_revision_id,
            FlowModel.current_dispatch_id == source_dispatch_id,
            FlowModel.waiting_cause == "none",
            FlowModel.control_revision == dispatch.flow_control_revision,
        )
        & exists().where(
            FlowNodeModel.flow_id == prompt.flow_id,
            FlowNodeModel.flow_revision_id == prompt.flow_revision_id,
            FlowNodeModel.node_key == prompt.node_key,
            FlowNodeModel.structural_kind == prompt.node_kind,
            FlowNodeModel.state == "running",
            FlowNodeModel.current_assignment_id == prompt.assignment_id,
            FlowNodeModel.provider_kind == dispatch.raw_provider_kind,
        )
        & exists().where(
            NodePlanRevisionModel.node_plan_revision_id == dispatch.node_plan_revision_id,
            NodePlanRevisionModel.flow_id == prompt.flow_id,
            NodePlanRevisionModel.flow_revision_id == prompt.flow_revision_id,
            NodePlanRevisionModel.provider_kind == dispatch.raw_provider_kind,
        )
        & exists().where(
            AssignmentModel.assignment_id == prompt.assignment_id,
            AssignmentModel.task_id == prompt.task_id,
            AssignmentModel.flow_id == prompt.flow_id,
            AssignmentModel.flow_revision_id == prompt.flow_revision_id,
            AssignmentModel.node_key == prompt.node_key,
            AssignmentModel.current_attempt_id == prompt.attempt_id,
            AssignmentModel.work_plan_revision == dispatch.assignment_work_plan_revision,
            AssignmentModel.superseded_at.is_(None),
        )
        & exists().where(
            AttemptModel.attempt_id == prompt.attempt_id,
            AttemptModel.assignment_id == prompt.assignment_id,
            AttemptModel.task_id == prompt.task_id,
            AttemptModel.flow_id == prompt.flow_id,
            AttemptModel.node_key == prompt.node_key,
            AttemptModel.status == "running",
        )
        & exists().where(
            TaskModel.task_id == prompt.task_id,
            TaskModel.task_root_path == dispatch.task_root_path,
            TaskModel.title == prompt.task_title,
            TaskModel.summary == prompt.task_summary,
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
            lineage.flow_id == prompt.flow_id,
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

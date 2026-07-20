from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.datetimes import UtcDateTime
from autoclaw.persistence.models.runtime.common import (
    CAPABILITY_DECISION_VALUES,
    CAPABILITY_SOURCE_VALUES,
    DISPATCH_CLOSED_REASON_VALUES,
    DISPATCH_OPENED_REASON_VALUES,
    DISPATCH_STARTING_CLOSE_REASON_VALUES,
    DISPATCH_STATUS_VALUES,
    NETWORK_ACCESS_VALUES,
    PROVIDER_NATIVE_ACCESS_VALUES,
    PROVIDER_SELECTION_BASIS_VALUES,
    PROVIDER_START_RETRY_KIND_VALUES,
    PROVIDER_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptCheckpointModel,
        AttemptModel,
    )
    from autoclaw.persistence.models.runtime.assignment.work_plan import (
        AssignmentWorkPlanModel,
    )
    from autoclaw.persistence.models.runtime.command_runs import CommandRunModel
    from autoclaw.persistence.models.runtime.dispatch.states import FlowStartSourceModel
    from autoclaw.persistence.models.runtime.dispatch.support import (
        AcceptedBoundaryModel,
        AssignmentDecisionModel,
    )
    from autoclaw.persistence.models.runtime.flow.runtime import FlowModel, FlowRevisionModel
    from autoclaw.persistence.models.runtime.human_requests import HumanRequestModel
    from autoclaw.persistence.models.runtime.task import TaskModel
    from autoclaw.persistence.models.runtime.waiting import FlowWaitModel


class DispatchTurnModel(RuntimeBase):
    __tablename__ = "dispatch_turns"
    __table_args__ = (
        UniqueConstraint("flow_id", "dispatch_id"),
        UniqueConstraint("dispatch_id", "task_id"),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "flow_id",
            "active_status_marker",
            name="uq_dispatch_turns_active_status_owner",
        ),
        UniqueConstraint("dispatch_id", "assignment_id"),
        UniqueConstraint("dispatch_id", "node_key"),
        UniqueConstraint("dispatch_id", "assignment_id", "attempt_id"),
        UniqueConstraint("dispatch_id", "task_id", "flow_id", "assignment_id", "attempt_id"),
        UniqueConstraint("flow_id", "dispatch_id", "opened_reason"),
        UniqueConstraint("flow_start_source_flow_id", "dispatch_id"),
        UniqueConstraint("predecessor_dispatch_id"),
        UniqueConstraint("predecessor_dispatch_id", "dispatch_id"),
        CheckConstraint(
            f"status IN ({sql_in(DISPATCH_STATUS_VALUES)})",
            name="ck_dispatch_turns_status",
        ),
        CheckConstraint(
            f"opened_reason IN ({sql_in(DISPATCH_OPENED_REASON_VALUES)})",
            name="ck_dispatch_turns_opened_reason",
        ),
        CheckConstraint(
            "(predecessor_dispatch_id IS NULL AND flow_start_source_flow_id = flow_id AND "
            "opened_reason IN ('root', 'operator_continue')) OR "
            "(predecessor_dispatch_id IS NOT NULL AND flow_start_source_flow_id IS NULL AND "
            "opened_reason != 'root')",
            name="ck_dispatch_turns_exact_source_shape",
        ),
        CheckConstraint(
            "predecessor_dispatch_id IS NULL OR predecessor_dispatch_id != dispatch_id",
            name="ck_dispatch_turns_predecessor_not_self",
        ),
        CheckConstraint(
            f"closed_reason IS NULL OR closed_reason IN ({sql_in(DISPATCH_CLOSED_REASON_VALUES)})",
            name="ck_dispatch_turns_closed_reason",
        ),
        CheckConstraint(
            f"requested_provider IN ({sql_in(PROVIDER_VALUES)}) AND "
            f"resolved_provider IN ({sql_in(PROVIDER_VALUES)}) AND "
            "requested_provider = resolved_provider",
            name="ck_dispatch_turns_provider_resolution",
        ),
        CheckConstraint(
            f"provider_selection_basis IN ({sql_in(PROVIDER_SELECTION_BASIS_VALUES)})",
            name="ck_dispatch_turns_provider_selection_basis",
        ),
        CheckConstraint(
            "provider_route_kind = resolved_provider AND "
            "((provider_route_kind IN ('codex', 'claude') AND gateway_profile IS NULL AND "
            "(model_override IS NULL OR length(trim(model_override)) > 0) AND "
            "(effort_override IS NULL OR length(trim(effort_override)) > 0)) OR "
            "(provider_route_kind = 'openclaw' AND gateway_profile IS NOT NULL AND "
            "length(trim(gateway_profile)) > 0 AND "
            "model_override IS NULL AND effort_override IS NULL))",
            name="ck_dispatch_turns_provider_route",
        ),
        CheckConstraint(
            "provider_start_revision >= 0 AND provider_start_attempt_count >= 0",
            name="ck_dispatch_turns_provider_start_revision",
        ),
        CheckConstraint(
            "provider_start_retry_kind IS NULL OR "
            f"provider_start_retry_kind IN ({sql_in(PROVIDER_START_RETRY_KIND_VALUES)})",
            name="ck_dispatch_turns_provider_start_retry_kind",
        ),
        CheckConstraint(
            "node_activity_revision >= 0",
            name="ck_dispatch_turns_node_activity_revision",
        ),
        CheckConstraint(
            "(status = 'starting' AND adapter_started_at IS NULL AND closed_at IS NULL AND "
            "closed_reason IS NULL AND next_provider_start_at IS NOT NULL AND "
            "provider_start_retry_kind IS NOT NULL) OR "
            "(status = 'open' AND adapter_started_at IS NOT NULL AND closed_at IS NULL AND "
            "closed_reason IS NULL AND next_provider_start_at IS NULL AND "
            "provider_start_retry_kind IS NULL AND provider_start_last_error_code IS NULL) OR "
            "(status = 'closed' AND closed_at IS NOT NULL AND closed_reason IS NOT NULL AND "
            "next_provider_start_at IS NULL AND provider_start_retry_kind IS NULL)",
            name="ck_dispatch_turns_lifecycle_fields",
        ),
        CheckConstraint(
            "closed_reason != 'watchdog_superseded' OR adapter_started_at IS NOT NULL",
            name="ck_dispatch_turns_watchdog_requires_open",
        ),
        CheckConstraint(
            "status != 'closed' OR adapter_started_at IS NOT NULL OR "
            f"closed_reason IN ({sql_in(DISPATCH_STARTING_CLOSE_REASON_VALUES)})",
            name="ck_dispatch_turns_starting_close_reason",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id"],
            ["assignments.task_id", "assignments.flow_id", "assignments.assignment_id"],
            name="fk_dispatch_turns_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "node_key"],
            ["assignments.assignment_id", "assignments.node_key"],
            name="fk_dispatch_turns_assignment_node_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "attempts.task_id",
                "attempts.flow_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
            ],
            name="fk_dispatch_turns_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "predecessor_dispatch_id"],
            ["dispatch_turns.flow_id", "dispatch_turns.dispatch_id"],
            name="fk_dispatch_turns_predecessor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "uq_dispatch_turns_one_first_per_flow",
            "flow_id",
            unique=True,
            sqlite_where=text("predecessor_dispatch_id IS NULL"),
            postgresql_where=text("predecessor_dispatch_id IS NULL"),
        ),
        Index(
            "uq_dispatch_turns_one_current_per_flow",
            "flow_id",
            unique=True,
            sqlite_where=text("status IN ('starting', 'open')"),
            postgresql_where=text("status IN ('starting', 'open')"),
        ),
        Index("ix_dispatch_turns_task_created_at", "task_id", "created_at"),
        Index("ix_dispatch_turns_start_due", "status", "next_provider_start_at"),
        Index("ix_dispatch_turns_watchdog_activity", "status", "last_node_activity_at"),
    )

    dispatch_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    node_key: Mapped[str] = mapped_column(String(255), index=True)
    flow_start_source_flow_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(
            "flow_start_sources.flow_id",
            name="fk_dispatch_turns_flow_start_source",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    predecessor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64))
    active_status_marker: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN status IN ('starting', 'open') THEN 1 ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    opened_reason: Mapped[str] = mapped_column(String(64))
    requested_provider: Mapped[str] = mapped_column(String(64))
    resolved_provider: Mapped[str] = mapped_column(String(64))
    provider_selection_basis: Mapped[str] = mapped_column(String(64))
    provider_route_kind: Mapped[str] = mapped_column(String(64))
    model_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effort_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_start_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provider_start_attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    next_provider_start_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(),
        nullable=True,
    )
    provider_start_retry_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_start_last_error_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    adapter_started_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(),
        nullable=True,
    )
    last_node_activity_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(),
        nullable=True,
    )
    node_activity_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        back_populates="dispatch_turns",
        foreign_keys=[flow_id],
        lazy="raise",
    )
    assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        primaryjoin=(
            "and_(DispatchTurnModel.task_id == AssignmentModel.task_id, "
            "DispatchTurnModel.flow_id == AssignmentModel.flow_id, "
            "DispatchTurnModel.assignment_id == AssignmentModel.assignment_id, "
            "DispatchTurnModel.node_key == AssignmentModel.node_key)"
        ),
        foreign_keys=[task_id, flow_id, assignment_id, node_key],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        back_populates="dispatch_turns",
        primaryjoin=(
            "and_(DispatchTurnModel.task_id == AttemptModel.task_id, "
            "DispatchTurnModel.flow_id == AttemptModel.flow_id, "
            "DispatchTurnModel.assignment_id == AttemptModel.assignment_id, "
            "DispatchTurnModel.attempt_id == AttemptModel.attempt_id)"
        ),
        foreign_keys=[task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    flow_start_source: Mapped[FlowStartSourceModel | None] = relationship(
        "FlowStartSourceModel",
        foreign_keys=[flow_start_source_flow_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    predecessor: Mapped[DispatchTurnModel | None] = relationship(
        back_populates="successors",
        foreign_keys=[flow_id, predecessor_dispatch_id],
        remote_side=lambda: [DispatchTurnModel.flow_id, DispatchTurnModel.dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    successors: Mapped[list[DispatchTurnModel]] = relationship(
        back_populates="predecessor",
        foreign_keys="[DispatchTurnModel.flow_id, DispatchTurnModel.predecessor_dispatch_id]",
        lazy="raise",
        viewonly=True,
    )
    prompt_refs: Mapped[DispatchPromptRefsModel | None] = relationship(
        back_populates="dispatch",
        foreign_keys="DispatchPromptRefsModel.dispatch_id",
        lazy="raise",
        uselist=False,
    )
    capability_set: Mapped[DispatchCapabilitySetModel | None] = relationship(
        back_populates="dispatch",
        foreign_keys="DispatchCapabilitySetModel.dispatch_id",
        lazy="raise",
        uselist=False,
    )
    node_invocations: Mapped[list[NodeInvocationModel]] = relationship(
        back_populates="dispatch",
        foreign_keys="[NodeInvocationModel.dispatch_id, NodeInvocationModel.task_id]",
        lazy="raise",
        order_by="NodeInvocationModel.started_at",
        viewonly=True,
    )
    created_flow_revisions: Mapped[list[FlowRevisionModel]] = relationship(
        "FlowRevisionModel",
        back_populates="created_by_dispatch",
        foreign_keys="[FlowRevisionModel.flow_id, FlowRevisionModel.created_by_dispatch_id]",
        lazy="raise",
        viewonly=True,
    )
    created_assignments: Mapped[list[AssignmentModel]] = relationship(
        "AssignmentModel",
        back_populates="created_by_dispatch",
        foreign_keys="[AssignmentModel.flow_id, AssignmentModel.created_by_dispatch_id]",
        lazy="raise",
        viewonly=True,
    )
    authored_checkpoints: Mapped[list[AttemptCheckpointModel]] = relationship(
        "AttemptCheckpointModel",
        back_populates="authoring_dispatch",
        foreign_keys=(
            "[AttemptCheckpointModel.authoring_dispatch_id, "
            "AttemptCheckpointModel.assignment_id, AttemptCheckpointModel.attempt_id]"
        ),
        lazy="raise",
        order_by="AttemptCheckpointModel.recorded_at",
        viewonly=True,
    )
    authored_work_plans: Mapped[list[AssignmentWorkPlanModel]] = relationship(
        "AssignmentWorkPlanModel",
        back_populates="authoring_dispatch",
        foreign_keys=(
            "[AssignmentWorkPlanModel.authoring_dispatch_id, AssignmentWorkPlanModel.assignment_id]"
        ),
        lazy="raise",
        viewonly=True,
    )
    assignment_decision: Mapped[AssignmentDecisionModel | None] = relationship(
        "AssignmentDecisionModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[AssignmentDecisionModel.source_dispatch_id, AssignmentDecisionModel.task_id, "
            "AssignmentDecisionModel.flow_id, AssignmentDecisionModel.assignment_id, "
            "AssignmentDecisionModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    accepted_boundary: Mapped[AcceptedBoundaryModel | None] = relationship(
        "AcceptedBoundaryModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[AcceptedBoundaryModel.source_dispatch_id, AcceptedBoundaryModel.task_id, "
            "AcceptedBoundaryModel.flow_id, AcceptedBoundaryModel.assignment_id, "
            "AcceptedBoundaryModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    human_request: Mapped[HumanRequestModel | None] = relationship(
        "HumanRequestModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[HumanRequestModel.source_dispatch_id, HumanRequestModel.task_id, "
            "HumanRequestModel.flow_id, HumanRequestModel.assignment_id, "
            "HumanRequestModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    command_run: Mapped[CommandRunModel | None] = relationship(
        "CommandRunModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[CommandRunModel.source_dispatch_id, CommandRunModel.task_id, "
            "CommandRunModel.flow_id, CommandRunModel.assignment_id, "
            "CommandRunModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    flow_wait: Mapped[FlowWaitModel | None] = relationship(
        "FlowWaitModel",
        back_populates="source_dispatch",
        foreign_keys="FlowWaitModel.source_dispatch_id",
        lazy="raise",
        uselist=False,
    )


class DispatchPromptRefsModel(RuntimeBase):
    __tablename__ = "dispatch_prompt_refs"
    __table_args__ = (
        CheckConstraint(
            "dynamic_input_version >= 1",
            name="ck_dispatch_prompt_refs_dynamic_input_version",
        ),
    )

    dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("dispatch_turns.dispatch_id"), primary_key=True
    )
    instructions_logical_path: Mapped[str] = mapped_column(Text)
    input_logical_path: Mapped[str] = mapped_column(Text)
    dynamic_input_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    dispatch: Mapped[DispatchTurnModel] = relationship(
        back_populates="prompt_refs",
        foreign_keys=[dispatch_id],
        lazy="raise",
    )


class DispatchCapabilitySetModel(RuntimeBase):
    __tablename__ = "dispatch_capability_sets"
    __table_args__ = (
        CheckConstraint(
            f"provider_native_access IN ({sql_in(PROVIDER_NATIVE_ACCESS_VALUES)})",
            name="ck_dispatch_capability_sets_provider_native_access",
        ),
        CheckConstraint(
            f"provider_native_access_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
            name="ck_dispatch_capability_sets_provider_native_source",
        ),
        CheckConstraint(
            f"network_access IN ({sql_in(NETWORK_ACCESS_VALUES)})",
            name="ck_dispatch_capability_sets_network_access",
        ),
        CheckConstraint(
            f"network_access_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
            name="ck_dispatch_capability_sets_network_source",
        ),
        *(
            CheckConstraint(
                f"{column} IN ({sql_in(CAPABILITY_DECISION_VALUES)})",
                name=f"ck_dispatch_capability_sets_{column}",
            )
            for column in (
                "human_direction",
                "human_approval",
                "human_input",
                "human_review",
                "command_run",
            )
        ),
    )

    dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("dispatch_turns.dispatch_id"), primary_key=True
    )
    provider_native_access: Mapped[str] = mapped_column(String(64))
    provider_native_access_source: Mapped[str] = mapped_column(String(64))
    network_access: Mapped[str] = mapped_column(String(64))
    network_access_source: Mapped[str] = mapped_column(String(64))
    human_direction: Mapped[str] = mapped_column(String(64))
    human_approval: Mapped[str] = mapped_column(String(64))
    human_input: Mapped[str] = mapped_column(String(64))
    human_review: Mapped[str] = mapped_column(String(64))
    command_run: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    dispatch: Mapped[DispatchTurnModel] = relationship(
        back_populates="capability_set",
        foreign_keys=[dispatch_id],
        lazy="raise",
    )


class NodeInvocationModel(RuntimeBase):
    __tablename__ = "node_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dispatch_id", "task_id"],
            ["dispatch_turns.dispatch_id", "dispatch_turns.task_id"],
            name="fk_node_invocations_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_node_invocations_task_started", "task_id", "started_at"),
    )

    invocation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), index=True)
    dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    logical_tool_name: Mapped[str] = mapped_column(String(255))
    outcome_code: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime())
    ended_at: Mapped[datetime] = mapped_column(UtcDateTime())
    dispatch: Mapped[DispatchTurnModel] = relationship(
        back_populates="node_invocations",
        foreign_keys=[dispatch_id, task_id],
        lazy="raise",
        viewonly=True,
    )
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        primaryjoin="NodeInvocationModel.task_id == TaskModel.task_id",
        foreign_keys=[task_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "DispatchCapabilitySetModel",
    "DispatchPromptRefsModel",
    "DispatchTurnModel",
    "NodeInvocationModel",
]

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

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    DISPATCH_CLOSED_REASON_VALUES,
    DISPATCH_OPENED_REASON_VALUES,
    DISPATCH_STARTING_CLOSE_REASON_VALUES,
    DISPATCH_STATUS_VALUES,
    PROVIDER_ROUTE_VALUE_SOURCE_VALUES,
    PROVIDER_SELECTION_BASIS_VALUES,
    PROVIDER_START_RETRY_KIND_VALUES,
    PROVIDER_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import (
        AssignmentModel,
        AttemptCheckpointModel,
        AttemptModel,
    )
    from banksia.persistence.models.runtime.assignment.work_plan import (
        AssignmentWorkPlanModel,
    )
    from banksia.persistence.models.runtime.command_runs import CommandRunModel
    from banksia.persistence.models.runtime.dispatch.capabilities import (
        DispatchCapabilitySetModel,
    )
    from banksia.persistence.models.runtime.dispatch.states import TaskStartSourceModel
    from banksia.persistence.models.runtime.dispatch.support import AcceptedBoundaryModel
    from banksia.persistence.models.runtime.human_requests import HumanRequestModel
    from banksia.persistence.models.runtime.task import TaskModel
    from banksia.persistence.models.runtime.team import TeamRevisionMemberModel
    from banksia.persistence.models.runtime.waiting import AttemptWaitModel


class DispatchTurnModel(RuntimeBase):
    __tablename__ = "dispatch_turns"
    __table_args__ = (
        UniqueConstraint("dispatch_id", "task_id"),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "active_status_marker",
            name="uq_dispatch_turns_active_status_owner",
        ),
        UniqueConstraint("dispatch_id", "assignment_id"),
        UniqueConstraint(
            "dispatch_id",
            "provider_route_kind",
            name="uq_dispatch_turns_provider_route_owner",
        ),
        UniqueConstraint("dispatch_id", "assignment_id", "attempt_id"),
        UniqueConstraint("dispatch_id", "task_id", "assignment_id", "attempt_id"),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "assignment_id",
            "attempt_id",
            "team_revision_id",
            name="uq_dispatch_turns_team_revision_owner",
        ),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "assignment_id",
            "attempt_id",
            "active_status_marker",
            name="uq_dispatch_turns_attempt_active_owner",
        ),
        UniqueConstraint("attempt_id", "dispatch_id", name="uq_dispatch_turns_attempt_dispatch"),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "assignment_id",
            "attempt_id",
            "team_revision_id",
            "member_id",
            "member_configuration_id",
            "member_branch_basis_id",
            name="uq_dispatch_turns_exact_selection",
        ),
        UniqueConstraint(
            "dispatch_id",
            "task_id",
            "assignment_id",
            "attempt_id",
            "predecessor_dispatch_id",
            name="uq_dispatch_turns_successor_owner",
        ),
        UniqueConstraint("task_start_source_task_id", "dispatch_id"),
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
            "(predecessor_dispatch_id IS NULL AND task_start_source_task_id = task_id AND "
            "opened_reason IN ('root', 'operator_continue')) OR "
            "(predecessor_dispatch_id IS NULL AND task_start_source_task_id IS NULL AND "
            "opened_reason IN ('delegation', 'semantic_retry')) OR "
            "(predecessor_dispatch_id IS NOT NULL AND task_start_source_task_id IS NULL AND "
            "opened_reason NOT IN ('root', 'delegation', 'semantic_retry'))",
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
            "gateway_profile_source IS NULL AND "
            f"model_source IN ({sql_in(PROVIDER_ROUTE_VALUE_SOURCE_VALUES)}) AND "
            f"effort_source IN ({sql_in(PROVIDER_ROUTE_VALUE_SOURCE_VALUES)}) AND "
            "(model_source = 'provider_configuration' OR model_override IS NOT NULL) AND "
            "(effort_source = 'provider_configuration' OR effort_override IS NOT NULL) AND "
            "(provider_selection_basis = 'explicit' OR "
            "(model_source = 'provider_configuration' AND "
            "effort_source = 'provider_configuration')) AND "
            "(model_override IS NULL OR length(trim(model_override)) > 0) AND "
            "(effort_override IS NULL OR length(trim(effort_override)) > 0)) OR "
            "(provider_route_kind = 'openclaw' AND gateway_profile IS NOT NULL AND "
            "length(trim(gateway_profile)) > 0 AND "
            "gateway_profile_source = 'provider_configuration' AND "
            "model_override IS NULL AND effort_override IS NULL AND "
            "model_source IS NULL AND effort_source IS NULL))",
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
            ["task_id", "assignment_id", "member_id"],
            ["assignments.task_id", "assignments.assignment_id", "assignments.member_id"],
            name="fk_dispatch_turns_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "team_revision_id",
                "member_id",
                "member_configuration_id",
                "member_branch_basis_id",
            ],
            [
                "team_revision_members.task_id",
                "team_revision_members.team_revision_id",
                "team_revision_members.member_id",
                "team_revision_members.member_configuration_id",
                "team_revision_members.member_branch_basis_id",
            ],
            name="fk_dispatch_turns_team_selection",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id"],
            ["attempts.task_id", "attempts.assignment_id", "attempts.attempt_id"],
            name="fk_dispatch_turns_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "predecessor_dispatch_id"],
            ["dispatch_turns.attempt_id", "dispatch_turns.dispatch_id"],
            name="fk_dispatch_turns_predecessor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "dispatch_id", "active_status_marker"],
            [
                "attempts.attempt_id",
                "attempts.current_dispatch_id",
                "attempts.current_dispatch_presence_marker",
            ],
            name="fk_dispatch_turns_current_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "uq_dispatch_turns_one_first_per_attempt",
            "attempt_id",
            unique=True,
            sqlite_where=text("predecessor_dispatch_id IS NULL"),
            postgresql_where=text("predecessor_dispatch_id IS NULL"),
        ),
        Index(
            "uq_dispatch_turns_one_current_per_attempt",
            "attempt_id",
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
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    team_revision_id: Mapped[str] = mapped_column(String(255), index=True)
    member_id: Mapped[str] = mapped_column(String(128), index=True)
    member_configuration_id: Mapped[str] = mapped_column(String(255))
    member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    task_start_source_task_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(
            "task_start_sources.task_id",
            name="fk_dispatch_turns_task_start_source",
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
    model_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effort_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effort_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_profile_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    adapter_started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_node_activity_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(),
        nullable=True,
    )
    node_activity_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task: Mapped[TaskModel] = relationship("TaskModel", foreign_keys=[task_id], lazy="raise")
    assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        primaryjoin=(
            "and_(DispatchTurnModel.task_id == AssignmentModel.task_id, "
            "DispatchTurnModel.assignment_id == AssignmentModel.assignment_id, "
            "DispatchTurnModel.member_id == AssignmentModel.member_id)"
        ),
        foreign_keys=[task_id, assignment_id, member_id],
        lazy="raise",
        viewonly=True,
    )
    team_selection: Mapped[TeamRevisionMemberModel] = relationship(
        "TeamRevisionMemberModel",
        foreign_keys=[
            task_id,
            team_revision_id,
            member_id,
            member_configuration_id,
            member_branch_basis_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        back_populates="dispatch_turns",
        primaryjoin=(
            "and_(DispatchTurnModel.task_id == AttemptModel.task_id, "
            "DispatchTurnModel.assignment_id == AttemptModel.assignment_id, "
            "DispatchTurnModel.attempt_id == AttemptModel.attempt_id)"
        ),
        foreign_keys=[task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    current_attempt: Mapped[AttemptModel | None] = relationship(
        "AttemptModel",
        primaryjoin=(
            "and_(DispatchTurnModel.attempt_id == AttemptModel.attempt_id, "
            "DispatchTurnModel.dispatch_id == AttemptModel.current_dispatch_id, "
            "DispatchTurnModel.active_status_marker == "
            "AttemptModel.current_dispatch_presence_marker)"
        ),
        foreign_keys=[attempt_id, dispatch_id, active_status_marker],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    task_start_source: Mapped[TaskStartSourceModel | None] = relationship(
        "TaskStartSourceModel",
        foreign_keys=[task_start_source_task_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    predecessor: Mapped[DispatchTurnModel | None] = relationship(
        back_populates="successors",
        foreign_keys=[attempt_id, predecessor_dispatch_id],
        remote_side=lambda: [DispatchTurnModel.attempt_id, DispatchTurnModel.dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    successors: Mapped[list[DispatchTurnModel]] = relationship(
        back_populates="predecessor",
        foreign_keys="[DispatchTurnModel.attempt_id, DispatchTurnModel.predecessor_dispatch_id]",
        lazy="raise",
        viewonly=True,
    )
    request: Mapped[DispatchRequestModel | None] = relationship(
        back_populates="dispatch",
        foreign_keys="DispatchRequestModel.dispatch_id",
        lazy="raise",
        uselist=False,
    )
    capability_set: Mapped[DispatchCapabilitySetModel | None] = relationship(
        back_populates="dispatch",
        foreign_keys=(
            "[DispatchCapabilitySetModel.dispatch_id, DispatchCapabilitySetModel.provider_kind]"
        ),
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
    created_assignments: Mapped[list[AssignmentModel]] = relationship(
        "AssignmentModel",
        back_populates="created_by_dispatch",
        foreign_keys="[AssignmentModel.task_id, AssignmentModel.created_by_dispatch_id]",
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
    accepted_boundary: Mapped[AcceptedBoundaryModel | None] = relationship(
        "AcceptedBoundaryModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[AcceptedBoundaryModel.source_dispatch_id, AcceptedBoundaryModel.task_id, "
            "AcceptedBoundaryModel.assignment_id, AcceptedBoundaryModel.attempt_id]"
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
            "HumanRequestModel.assignment_id, HumanRequestModel.attempt_id]"
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
            "CommandRunModel.assignment_id, CommandRunModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    attempt_wait: Mapped[AttemptWaitModel | None] = relationship(
        "AttemptWaitModel",
        back_populates="source_dispatch",
        foreign_keys=(
            "[AttemptWaitModel.source_dispatch_id, AttemptWaitModel.task_id, "
            "AttemptWaitModel.assignment_id, AttemptWaitModel.attempt_id]"
        ),
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


class DispatchRequestModel(RuntimeBase):
    __tablename__ = "dispatch_requests"

    dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("dispatch_turns.dispatch_id"),
        primary_key=True,
    )
    instructions: Mapped[str] = mapped_column(Text)
    input: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    dispatch: Mapped[DispatchTurnModel] = relationship(
        back_populates="request",
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


__all__ = ["DispatchRequestModel", "DispatchTurnModel", "NodeInvocationModel"]

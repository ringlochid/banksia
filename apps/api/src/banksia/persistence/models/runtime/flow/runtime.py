from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    FLOW_STATUS_VALUES,
    FLOW_TERMINAL_OUTCOME_VALUES,
    STRUCTURAL_REVISION_CAUSE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import AssignmentModel
    from banksia.persistence.models.runtime.dispatch.states import FlowStartSourceModel
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.flow.graph import (
        FlowNodeModel,
        NodePlanRevisionModel,
    )
    from banksia.persistence.models.runtime.task import CompiledPlanModel, TaskModel
    from banksia.persistence.models.runtime.task_events import TaskEventModel


class FlowModel(RuntimeBase):
    __tablename__ = "flows"
    __table_args__ = (
        UniqueConstraint("flow_id", "task_id"),
        CheckConstraint(
            f"status IN ({sql_in(FLOW_STATUS_VALUES)})",
            name="ck_flows_status",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR "
            f"terminal_outcome IN ({sql_in(FLOW_TERMINAL_OUTCOME_VALUES)})",
            name="ck_flows_terminal_outcome_value",
        ),
        CheckConstraint(
            "(status = 'completed' AND terminal_outcome IS NOT NULL) OR "
            "(status != 'completed' AND terminal_outcome IS NULL)",
            name="ck_flows_terminal_outcome_status",
        ),
        CheckConstraint("control_revision >= 0", name="ck_flows_control_revision"),
        CheckConstraint(
            "(status = 'paused' AND pause_reason IS NOT NULL AND paused_at IS NOT NULL) OR "
            "(status != 'paused' AND pause_reason IS NULL AND pause_details IS NULL AND "
            "paused_at IS NULL AND paused_by_actor_ref IS NULL)",
            name="ck_flows_pause_state",
        ),
        ForeignKeyConstraint(
            ["task_id", "compiled_plan_id"],
            ["compiled_plans.task_id", "compiled_plans.compiled_plan_id"],
            name="fk_flows_compiled_plan_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "active_flow_revision_id"],
            ["flow_revisions.flow_id", "flow_revisions.flow_revision_id"],
            name="fk_flows_active_flow_revision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_flows_status_updated_at", "status", "updated_at"),
    )

    flow_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    compiled_plan_id: Mapped[str] = mapped_column(ForeignKey("compiled_plans.compiled_plan_id"))
    status: Mapped[str] = mapped_column(String(64), index=True)
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_flow_revision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    control_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pause_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pause_details: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    paused_by_actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        back_populates="flow",
        foreign_keys=[task_id],
        lazy="raise",
    )
    compiled_plan: Mapped[CompiledPlanModel] = relationship(
        "CompiledPlanModel",
        foreign_keys=[task_id, compiled_plan_id],
        lazy="raise",
        viewonly=True,
    )
    revisions: Mapped[list[FlowRevisionModel]] = relationship(
        back_populates="flow",
        foreign_keys="FlowRevisionModel.flow_id",
        lazy="raise",
        order_by="FlowRevisionModel.revision_index",
    )
    active_revision: Mapped[FlowRevisionModel | None] = relationship(
        primaryjoin=lambda: and_(
            FlowModel.flow_id == FlowRevisionModel.flow_id,
            FlowModel.active_flow_revision_id == FlowRevisionModel.flow_revision_id,
        ),
        foreign_keys=[active_flow_revision_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    dispatch_turns: Mapped[list[DispatchTurnModel]] = relationship(
        "DispatchTurnModel",
        back_populates="flow",
        foreign_keys="DispatchTurnModel.flow_id",
        lazy="raise",
        order_by="DispatchTurnModel.created_at",
    )
    start_source: Mapped[FlowStartSourceModel | None] = relationship(
        "FlowStartSourceModel",
        back_populates="flow",
        foreign_keys="FlowStartSourceModel.flow_id",
        lazy="raise",
        uselist=False,
    )
    assignments: Mapped[list[AssignmentModel]] = relationship(
        "AssignmentModel",
        back_populates="flow",
        foreign_keys="AssignmentModel.flow_id",
        lazy="raise",
    )


class FlowRevisionModel(RuntimeBase):
    __tablename__ = "flow_revisions"
    __table_args__ = (
        UniqueConstraint("flow_id", "revision_no"),
        UniqueConstraint("flow_id", "flow_revision_id"),
        UniqueConstraint(
            "flow_id",
            "flow_revision_id",
            "parent_flow_revision_id",
            name="uq_flow_revisions_exact_parent",
        ),
        ForeignKeyConstraint(
            ["flow_id", "parent_flow_revision_id"],
            ["flow_revisions.flow_id", "flow_revisions.flow_revision_id"],
            name="fk_flow_revisions_parent_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "created_by_dispatch_id"],
            ["dispatch_turns.flow_id", "dispatch_turns.dispatch_id"],
            name="fk_flow_revisions_authoring_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision_no >= 1", name="ck_flow_revisions_revision_no"),
        CheckConstraint(
            f"cause IN ({sql_in(STRUCTURAL_REVISION_CAUSE_VALUES)})",
            name="ck_flow_revisions_cause",
        ),
    )

    flow_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    revision_index: Mapped[int] = mapped_column("revision_no", Integer)
    parent_flow_revision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_compiled_plan_id: Mapped[str] = mapped_column(
        ForeignKey("compiled_plans.compiled_plan_id")
    )
    cause: Mapped[str] = mapped_column(String(64))
    created_by_dispatch_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    adopted_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    flow: Mapped[FlowModel] = relationship(
        back_populates="revisions",
        foreign_keys=[flow_id],
        lazy="raise",
    )
    parent_revision: Mapped[FlowRevisionModel | None] = relationship(
        back_populates="child_revisions",
        foreign_keys=[flow_id, parent_flow_revision_id],
        remote_side=lambda: [FlowRevisionModel.flow_id, FlowRevisionModel.flow_revision_id],
        lazy="raise",
        viewonly=True,
    )
    child_revisions: Mapped[list[FlowRevisionModel]] = relationship(
        back_populates="parent_revision",
        foreign_keys="[FlowRevisionModel.flow_id, FlowRevisionModel.parent_flow_revision_id]",
        lazy="raise",
        order_by="FlowRevisionModel.revision_index",
        viewonly=True,
    )
    source_compiled_plan: Mapped[CompiledPlanModel] = relationship(
        "CompiledPlanModel",
        foreign_keys=[source_compiled_plan_id],
        lazy="raise",
    )
    created_by_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        back_populates="created_flow_revisions",
        foreign_keys=[flow_id, created_by_dispatch_id],
        lazy="raise",
        viewonly=True,
    )
    nodes: Mapped[list[FlowNodeModel]] = relationship(
        "FlowNodeModel",
        back_populates="flow_revision",
        foreign_keys="[FlowNodeModel.flow_id, FlowNodeModel.flow_revision_id]",
        lazy="raise",
        order_by="FlowNodeModel.order_index",
    )
    node_plan_revisions: Mapped[list[NodePlanRevisionModel]] = relationship(
        "NodePlanRevisionModel",
        back_populates="flow_revision",
        primaryjoin=(
            "and_(FlowRevisionModel.flow_id == NodePlanRevisionModel.flow_id, "
            "FlowRevisionModel.flow_revision_id == NodePlanRevisionModel.flow_revision_id)"
        ),
        foreign_keys="[NodePlanRevisionModel.flow_id, NodePlanRevisionModel.flow_revision_id]",
        lazy="raise",
        viewonly=True,
    )
    task_events: Mapped[list[TaskEventModel]] = relationship(
        "TaskEventModel",
        back_populates="flow_revision",
        foreign_keys="TaskEventModel.flow_revision_id",
        lazy="raise",
        order_by="TaskEventModel.event_seq",
    )


__all__ = ["FlowModel", "FlowRevisionModel"]

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
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.registry import WorkflowRevisionModel
from banksia.persistence.models.runtime.common import (
    NODE_KIND_VALUES,
    PROVIDER_VALUES,
    WORKSPACE_BINDING_MODE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.dispatch.support import (
        AcceptedBoundaryModel,
    )
    from banksia.persistence.models.runtime.flow.runtime import FlowModel
    from banksia.persistence.models.runtime.task_events import (
        TaskEventModel,
        TaskEventStreamHeadModel,
    )
    from banksia.persistence.models.runtime.team import TeamRevisionModel


class TaskModel(RuntimeBase):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_key", "workflow_revision_no", "workflow_content_hash"],
            [
                "workflow_revisions.workflow_key",
                "workflow_revisions.revision_no",
                "workflow_revisions.content_hash",
            ],
            name="fk_tasks_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "current_team_revision_id",
                "workflow_key",
                "workflow_revision_no",
                "workflow_content_hash",
            ],
            [
                "team_revisions.task_id",
                "team_revisions.team_revision_id",
                "team_revisions.workflow_key",
                "team_revisions.workflow_revision_no",
                "team_revisions.workflow_content_hash",
            ],
            name="fk_tasks_current_team_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["result_boundary_id", "task_id"],
            [
                "accepted_boundaries.accepted_boundary_id",
                "accepted_boundaries.task_id",
            ],
            name="fk_tasks_result_boundary",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("workflow_revision_no >= 1", name="ck_tasks_workflow_revision_no"),
        CheckConstraint(
            "max_child_assignments_per_assignment >= 0",
            name="ck_tasks_max_child_assignments_per_assignment",
        ),
        CheckConstraint(
            "max_retries_per_assignment >= 0",
            name="ck_tasks_max_retries_per_assignment",
        ),
        CheckConstraint("max_wave_members >= 1", name="ck_tasks_max_wave_members"),
        Index("ix_tasks_workflow_key", "workflow_key"),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(String(255))
    workflow_revision_no: Mapped[int] = mapped_column(Integer)
    workflow_content_hash: Mapped[str] = mapped_column(String(64))
    current_team_revision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_boundary_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_child_assignments_per_assignment: Mapped[int] = mapped_column(
        Integer,
        default=20,
        server_default="20",
    )
    max_retries_per_assignment: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )
    max_wave_members: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    task_root_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    workspace_binding: Mapped[WorkspaceBindingModel | None] = relationship(
        back_populates="task",
        foreign_keys="WorkspaceBindingModel.task_id",
        lazy="raise",
        uselist=False,
    )
    compiled_plan: Mapped[CompiledPlanModel | None] = relationship(
        back_populates="task",
        foreign_keys="CompiledPlanModel.task_id",
        lazy="raise",
        uselist=False,
    )
    flow: Mapped[FlowModel | None] = relationship(
        "FlowModel",
        back_populates="task",
        foreign_keys="FlowModel.task_id",
        lazy="raise",
        uselist=False,
    )
    event_stream_head: Mapped[TaskEventStreamHeadModel | None] = relationship(
        "TaskEventStreamHeadModel",
        back_populates="task",
        foreign_keys="TaskEventStreamHeadModel.task_id",
        lazy="raise",
        uselist=False,
    )
    task_events: Mapped[list[TaskEventModel]] = relationship(
        "TaskEventModel",
        back_populates="task",
        foreign_keys="TaskEventModel.task_id",
        lazy="raise",
        order_by="TaskEventModel.event_seq",
    )
    workflow_revision: Mapped[WorkflowRevisionModel] = relationship(
        "WorkflowRevisionModel",
        foreign_keys=[workflow_key, workflow_revision_no, workflow_content_hash],
        lazy="raise",
        viewonly=True,
    )
    current_team_revision: Mapped[TeamRevisionModel | None] = relationship(
        "TeamRevisionModel",
        foreign_keys=[
            task_id,
            current_team_revision_id,
            workflow_key,
            workflow_revision_no,
            workflow_content_hash,
        ],
        lazy="raise",
        viewonly=True,
    )
    result_boundary: Mapped[AcceptedBoundaryModel | None] = relationship(
        "AcceptedBoundaryModel",
        foreign_keys=[result_boundary_id, task_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


class WorkspaceBindingModel(RuntimeBase):
    __tablename__ = "workspace_bindings"
    __table_args__ = (
        CheckConstraint(
            f"binding_mode IN ({sql_in(WORKSPACE_BINDING_MODE_VALUES)})",
            name="ck_workspace_bindings_mode",
        ),
    )

    workspace_binding_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    binding_mode: Mapped[str] = mapped_column(String(64))
    normalized_root_path: Mapped[str] = mapped_column(Text)
    bound_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        back_populates="workspace_binding",
        foreign_keys=[task_id],
        lazy="raise",
    )


class CompiledPlanModel(RuntimeBase):
    __tablename__ = "compiled_plans"
    __table_args__ = (
        UniqueConstraint("task_id", "compiled_plan_id"),
        ForeignKeyConstraint(
            ["workflow_key", "workflow_revision_no"],
            ["workflow_revisions.workflow_key", "workflow_revisions.revision_no"],
            name="fk_compiled_plans_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    compiled_plan_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    workflow_key: Mapped[str] = mapped_column(String(255))
    workflow_revision_no: Mapped[int] = mapped_column(Integer)
    compiler_version: Mapped[str] = mapped_column(String(255))
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        back_populates="compiled_plan",
        foreign_keys=[task_id],
        lazy="raise",
    )
    workflow_revision: Mapped[WorkflowRevisionModel] = relationship(
        "WorkflowRevisionModel",
        primaryjoin=lambda: and_(
            CompiledPlanModel.workflow_key == WorkflowRevisionModel.workflow_key,
            CompiledPlanModel.workflow_revision_no == WorkflowRevisionModel.revision_no,
        ),
        foreign_keys=[workflow_key, workflow_revision_no],
        lazy="raise",
        viewonly=True,
    )
    nodes: Mapped[list[CompiledPlanNodeModel]] = relationship(
        back_populates="compiled_plan",
        foreign_keys="CompiledPlanNodeModel.compiled_plan_id",
        lazy="raise",
        order_by="CompiledPlanNodeModel.order_index",
    )


class CompiledPlanNodeModel(RuntimeBase):
    __tablename__ = "compiled_plan_nodes"
    __table_args__ = (
        UniqueConstraint("compiled_plan_id", "node_key"),
        UniqueConstraint("task_id", "compiled_plan_id", "node_key"),
        CheckConstraint(
            f"structural_kind IN ({sql_in(NODE_KIND_VALUES)})",
            name="ck_compiled_plan_nodes_structural_kind",
        ),
        CheckConstraint(
            f"provider_kind IS NULL OR provider_kind IN ({sql_in(PROVIDER_VALUES)})",
            name="ck_compiled_plan_nodes_provider_kind",
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
            name="fk_compiled_plan_nodes_team_selection",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["compiled_plan_id", "parent_node_key"],
            ["compiled_plan_nodes.compiled_plan_id", "compiled_plan_nodes.node_key"],
            name="fk_compiled_plan_nodes_parent",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    compiled_plan_node_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    compiled_plan_id: Mapped[str] = mapped_column(ForeignKey("compiled_plans.compiled_plan_id"))
    task_id: Mapped[str] = mapped_column(String(255), index=True)
    team_revision_id: Mapped[str] = mapped_column(String(255))
    member_id: Mapped[str] = mapped_column(String(128))
    member_configuration_id: Mapped[str] = mapped_column(String(255))
    member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    member_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_key: Mapped[str] = mapped_column(String(255))
    parent_node_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    structural_kind: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    node_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    child_node_keys_json: Mapped[list[str]] = mapped_column(JSON(none_as_null=True))
    provider_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)
    compiled_plan: Mapped[CompiledPlanModel] = relationship(
        back_populates="nodes",
        foreign_keys=[compiled_plan_id],
        lazy="raise",
    )
    parent: Mapped[CompiledPlanNodeModel | None] = relationship(
        back_populates="children",
        primaryjoin=lambda: and_(
            CompiledPlanNodeModel.compiled_plan_id == CompiledPlanNodeModel.compiled_plan_id,
            CompiledPlanNodeModel.parent_node_key == CompiledPlanNodeModel.node_key,
        ),
        foreign_keys=[compiled_plan_id, parent_node_key],
        remote_side=lambda: [
            CompiledPlanNodeModel.compiled_plan_id,
            CompiledPlanNodeModel.node_key,
        ],
        lazy="raise",
        viewonly=True,
    )
    children: Mapped[list[CompiledPlanNodeModel]] = relationship(
        back_populates="parent",
        foreign_keys=(
            "[CompiledPlanNodeModel.compiled_plan_id, CompiledPlanNodeModel.parent_node_key]"
        ),
        lazy="raise",
        order_by="CompiledPlanNodeModel.order_index",
        viewonly=True,
    )
    team_selection: Mapped[object] = relationship(
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


__all__ = [
    "CompiledPlanModel",
    "CompiledPlanNodeModel",
    "TaskModel",
    "WorkspaceBindingModel",
]

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

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.datetimes import UtcDateTime
from autoclaw.persistence.models.registry import (
    PolicyRevisionModel,
    RoleRevisionModel,
    WorkflowRevisionModel,
)
from autoclaw.persistence.models.runtime.common import (
    NODE_KIND_VALUES,
    PROVIDER_VALUES,
    WORKSPACE_BINDING_MODE_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.flow.runtime import FlowModel
    from autoclaw.persistence.models.runtime.task_events import (
        TaskEventModel,
        TaskEventStreamHeadModel,
    )


class TaskModel(RuntimeBase):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_title", "title"),
        Index("ix_tasks_workflow_key", "workflow_key"),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_key: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    task_compose: Mapped[TaskComposeModel | None] = relationship(
        back_populates="task",
        foreign_keys="TaskComposeModel.task_id",
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


class TaskComposeModel(RuntimeBase):
    __tablename__ = "task_composes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_key", "workflow_revision_no"],
            ["workflow_revisions.workflow_key", "workflow_revisions.revision_no"],
            name="fk_task_composes_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "compiled_plan_id"],
            ["compiled_plans.task_id", "compiled_plans.compiled_plan_id"],
            name="fk_task_composes_compiled_plan_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    task_compose_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    workflow_key: Mapped[str] = mapped_column(String(255))
    workflow_revision_no: Mapped[int] = mapped_column(Integer)
    compiled_plan_id: Mapped[str] = mapped_column(String(255))
    compose_payload: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        back_populates="task_compose",
        foreign_keys=[task_id],
        lazy="raise",
    )
    workflow_revision: Mapped[WorkflowRevisionModel] = relationship(
        "WorkflowRevisionModel",
        primaryjoin=lambda: and_(
            TaskComposeModel.workflow_key == WorkflowRevisionModel.workflow_key,
            TaskComposeModel.workflow_revision_no == WorkflowRevisionModel.revision_no,
        ),
        foreign_keys=[workflow_key, workflow_revision_no],
        lazy="raise",
        viewonly=True,
    )
    compiled_plan: Mapped[CompiledPlanModel] = relationship(
        back_populates="task_compose",
        foreign_keys=[task_id, compiled_plan_id],
        lazy="raise",
        viewonly=True,
    )


class CompiledPlanModel(RuntimeBase):
    __tablename__ = "compiled_plans"
    __table_args__ = (
        UniqueConstraint("task_id", "compiled_plan_id"),
        ForeignKeyConstraint(
            ["workflow_key", "definition_revision_no"],
            ["workflow_revisions.workflow_key", "workflow_revisions.revision_no"],
            name="fk_compiled_plans_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    compiled_plan_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    workflow_key: Mapped[str] = mapped_column(String(255))
    definition_revision_no: Mapped[int] = mapped_column(Integer)
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
            CompiledPlanModel.definition_revision_no == WorkflowRevisionModel.revision_no,
        ),
        foreign_keys=[workflow_key, definition_revision_no],
        lazy="raise",
        viewonly=True,
    )
    task_compose: Mapped[TaskComposeModel | None] = relationship(
        back_populates="compiled_plan",
        foreign_keys="[TaskComposeModel.task_id, TaskComposeModel.compiled_plan_id]",
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    nodes: Mapped[list[CompiledPlanNodeModel]] = relationship(
        back_populates="compiled_plan",
        foreign_keys="CompiledPlanNodeModel.compiled_plan_id",
        lazy="raise",
        order_by="CompiledPlanNodeModel.order_index",
    )
    edges: Mapped[list[CompiledPlanEdgeModel]] = relationship(
        back_populates="compiled_plan",
        foreign_keys="CompiledPlanEdgeModel.compiled_plan_id",
        lazy="raise",
        order_by="CompiledPlanEdgeModel.order_index",
    )


class CompiledPlanNodeModel(RuntimeBase):
    __tablename__ = "compiled_plan_nodes"
    __table_args__ = (
        UniqueConstraint("compiled_plan_id", "node_key"),
        CheckConstraint(
            f"structural_kind IN ({sql_in(NODE_KIND_VALUES)})",
            name="ck_compiled_plan_nodes_structural_kind",
        ),
        CheckConstraint(
            f"provider_kind IS NULL OR provider_kind IN ({sql_in(PROVIDER_VALUES)})",
            name="ck_compiled_plan_nodes_provider_kind",
        ),
        ForeignKeyConstraint(
            ["role_key", "role_revision_no"],
            ["role_revisions.role_key", "role_revisions.revision_no"],
            name="fk_compiled_plan_nodes_role_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["policy_key", "policy_revision_no"],
            ["policy_revisions.policy_key", "policy_revisions.revision_no"],
            name="fk_compiled_plan_nodes_policy_revision",
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
    node_key: Mapped[str] = mapped_column(String(255))
    parent_node_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    structural_kind: Mapped[str] = mapped_column(String(64))
    role_key: Mapped[str] = mapped_column(String(255))
    role_revision_no: Mapped[int] = mapped_column(Integer)
    role_description: Mapped[str] = mapped_column(Text)
    role_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_key: Mapped[str] = mapped_column(String(255))
    policy_revision_no: Mapped[int] = mapped_column(Integer)
    policy_description: Mapped[str] = mapped_column(Text)
    policy_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    node_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    child_node_keys_json: Mapped[list[str]] = mapped_column(JSON(none_as_null=True))
    consumes_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    produces_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    criteria_json: Mapped[list[dict[str, object]]] = mapped_column(JSON(none_as_null=True))
    child_defaults_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
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
    role_revision: Mapped[RoleRevisionModel] = relationship(
        "RoleRevisionModel",
        primaryjoin=lambda: and_(
            CompiledPlanNodeModel.role_key == RoleRevisionModel.role_key,
            CompiledPlanNodeModel.role_revision_no == RoleRevisionModel.revision_no,
        ),
        foreign_keys=[role_key, role_revision_no],
        lazy="raise",
        viewonly=True,
    )
    policy_revision: Mapped[PolicyRevisionModel] = relationship(
        "PolicyRevisionModel",
        primaryjoin=lambda: and_(
            CompiledPlanNodeModel.policy_key == PolicyRevisionModel.policy_key,
            CompiledPlanNodeModel.policy_revision_no == PolicyRevisionModel.revision_no,
        ),
        foreign_keys=[policy_key, policy_revision_no],
        lazy="raise",
        viewonly=True,
    )
    outgoing_edges: Mapped[list[CompiledPlanEdgeModel]] = relationship(
        back_populates="provider_node",
        primaryjoin=lambda: and_(
            CompiledPlanNodeModel.compiled_plan_id == CompiledPlanEdgeModel.compiled_plan_id,
            CompiledPlanNodeModel.node_key == CompiledPlanEdgeModel.provider_node_key,
        ),
        foreign_keys=(
            "[CompiledPlanEdgeModel.compiled_plan_id, CompiledPlanEdgeModel.provider_node_key]"
        ),
        lazy="raise",
        order_by="CompiledPlanEdgeModel.order_index",
        viewonly=True,
    )
    incoming_edges: Mapped[list[CompiledPlanEdgeModel]] = relationship(
        back_populates="consumer_node",
        primaryjoin=lambda: and_(
            CompiledPlanNodeModel.compiled_plan_id == CompiledPlanEdgeModel.compiled_plan_id,
            CompiledPlanNodeModel.node_key == CompiledPlanEdgeModel.consumer_node_key,
        ),
        foreign_keys=(
            "[CompiledPlanEdgeModel.compiled_plan_id, CompiledPlanEdgeModel.consumer_node_key]"
        ),
        lazy="raise",
        order_by="CompiledPlanEdgeModel.order_index",
        viewonly=True,
    )


class CompiledPlanEdgeModel(RuntimeBase):
    __tablename__ = "compiled_plan_edges"
    __table_args__ = (
        UniqueConstraint("compiled_plan_id", "consumer_node_key", "kind", "slot"),
        ForeignKeyConstraint(
            ["compiled_plan_id", "provider_node_key"],
            ["compiled_plan_nodes.compiled_plan_id", "compiled_plan_nodes.node_key"],
            name="fk_compiled_plan_edges_provider_node",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["compiled_plan_id", "consumer_node_key"],
            ["compiled_plan_nodes.compiled_plan_id", "compiled_plan_nodes.node_key"],
            name="fk_compiled_plan_edges_consumer_node",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    compiled_plan_edge_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    compiled_plan_id: Mapped[str] = mapped_column(ForeignKey("compiled_plans.compiled_plan_id"))
    provider_node_key: Mapped[str] = mapped_column(String(255))
    consumer_node_key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    slot: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer)
    compiled_plan: Mapped[CompiledPlanModel] = relationship(
        back_populates="edges",
        foreign_keys=[compiled_plan_id],
        lazy="raise",
    )
    provider_node: Mapped[CompiledPlanNodeModel] = relationship(
        back_populates="outgoing_edges",
        primaryjoin=lambda: and_(
            CompiledPlanEdgeModel.compiled_plan_id == CompiledPlanNodeModel.compiled_plan_id,
            CompiledPlanEdgeModel.provider_node_key == CompiledPlanNodeModel.node_key,
        ),
        foreign_keys=[compiled_plan_id, provider_node_key],
        lazy="raise",
        viewonly=True,
    )
    consumer_node: Mapped[CompiledPlanNodeModel] = relationship(
        back_populates="incoming_edges",
        primaryjoin=lambda: and_(
            CompiledPlanEdgeModel.compiled_plan_id == CompiledPlanNodeModel.compiled_plan_id,
            CompiledPlanEdgeModel.consumer_node_key == CompiledPlanNodeModel.node_key,
        ),
        foreign_keys=[compiled_plan_id, consumer_node_key],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "CompiledPlanEdgeModel",
    "CompiledPlanModel",
    "CompiledPlanNodeModel",
    "TaskComposeModel",
    "TaskModel",
    "WorkspaceBindingModel",
]

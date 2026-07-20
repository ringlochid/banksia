from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.registry import PolicyRevisionModel, RoleRevisionModel
from autoclaw.persistence.models.runtime.common import (
    FLOW_EDGE_KIND_VALUES,
    NODE_KIND_VALUES,
    NODE_STATE_VALUES,
    PROVIDER_VALUES,
    sql_in,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.execution import AssignmentModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowRevisionModel


class FlowNodeModel(RuntimeBase):
    __tablename__ = "flow_nodes"
    __table_args__ = (
        UniqueConstraint("flow_id", "flow_revision_id", "flow_node_id"),
        UniqueConstraint("flow_revision_id", "node_key"),
        CheckConstraint(
            f"node_kind IN ({sql_in(NODE_KIND_VALUES)})",
            name="ck_flow_nodes_node_kind",
        ),
        CheckConstraint(
            f"state IN ({sql_in(NODE_STATE_VALUES)})",
            name="ck_flow_nodes_state",
        ),
        CheckConstraint(
            f"provider_kind IS NULL OR provider_kind IN ({sql_in(PROVIDER_VALUES)})",
            name="ck_flow_nodes_provider_kind",
        ),
        ForeignKeyConstraint(
            ["flow_id", "flow_revision_id"],
            ["flow_revisions.flow_id", "flow_revisions.flow_revision_id"],
            name="fk_flow_nodes_flow_revision_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["role_key", "role_revision_no"],
            ["role_revisions.role_key", "role_revisions.revision_no"],
            name="fk_flow_nodes_role_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["policy_key", "policy_revision_no"],
            ["policy_revisions.policy_key", "policy_revisions.revision_no"],
            name="fk_flow_nodes_policy_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_revision_id", "parent_node_key"],
            ["flow_nodes.flow_revision_id", "flow_nodes.node_key"],
            name="fk_flow_nodes_parent",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["current_assignment_id", "flow_node_id"],
            ["assignments.assignment_id", "assignments.flow_node_id"],
            name="fk_flow_nodes_current_assignment_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    flow_node_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    flow_revision_id: Mapped[str] = mapped_column(String(255))
    node_key: Mapped[str] = mapped_column(String(255))
    parent_node_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    structural_kind: Mapped[str] = mapped_column("node_kind", String(64))
    role_key: Mapped[str] = mapped_column(String(255))
    role_revision_no: Mapped[int] = mapped_column(Integer)
    role_description: Mapped[str] = mapped_column(Text)
    role_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_key: Mapped[str] = mapped_column(String(255))
    policy_revision_no: Mapped[int] = mapped_column(Integer)
    policy_description: Mapped[str] = mapped_column(Text)
    policy_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    state: Mapped[str] = mapped_column(String(64), default="ready")
    current_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)
    flow_revision: Mapped[FlowRevisionModel] = relationship(
        "FlowRevisionModel",
        back_populates="nodes",
        foreign_keys=[flow_id, flow_revision_id],
        lazy="raise",
    )
    parent: Mapped[FlowNodeModel | None] = relationship(
        back_populates="children",
        foreign_keys=[flow_revision_id, parent_node_key],
        remote_side=lambda: [FlowNodeModel.flow_revision_id, FlowNodeModel.node_key],
        lazy="raise",
        viewonly=True,
    )
    children: Mapped[list[FlowNodeModel]] = relationship(
        back_populates="parent",
        foreign_keys="[FlowNodeModel.flow_revision_id, FlowNodeModel.parent_node_key]",
        lazy="raise",
        order_by="FlowNodeModel.order_index",
        viewonly=True,
    )
    role_revision: Mapped[RoleRevisionModel] = relationship(
        "RoleRevisionModel",
        primaryjoin=lambda: and_(
            FlowNodeModel.role_key == RoleRevisionModel.role_key,
            FlowNodeModel.role_revision_no == RoleRevisionModel.revision_no,
        ),
        foreign_keys=[role_key, role_revision_no],
        lazy="raise",
        viewonly=True,
    )
    policy_revision: Mapped[PolicyRevisionModel] = relationship(
        "PolicyRevisionModel",
        primaryjoin=lambda: and_(
            FlowNodeModel.policy_key == PolicyRevisionModel.policy_key,
            FlowNodeModel.policy_revision_no == PolicyRevisionModel.revision_no,
        ),
        foreign_keys=[policy_key, policy_revision_no],
        lazy="raise",
        viewonly=True,
    )
    assignments: Mapped[list[AssignmentModel]] = relationship(
        "AssignmentModel",
        back_populates="flow_node",
        foreign_keys=(
            "[AssignmentModel.flow_id, AssignmentModel.flow_revision_id, "
            "AssignmentModel.flow_node_id]"
        ),
        lazy="raise",
        viewonly=True,
    )
    current_assignment: Mapped[AssignmentModel | None] = relationship(
        "AssignmentModel",
        primaryjoin=(
            "and_(FlowNodeModel.flow_node_id == AssignmentModel.flow_node_id, "
            "FlowNodeModel.current_assignment_id == AssignmentModel.assignment_id)"
        ),
        foreign_keys=[current_assignment_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )
    plan_revision: Mapped[NodePlanRevisionModel | None] = relationship(
        back_populates="flow_node",
        foreign_keys=(
            "[NodePlanRevisionModel.flow_id, NodePlanRevisionModel.flow_revision_id, "
            "NodePlanRevisionModel.flow_node_id]"
        ),
        lazy="raise",
        uselist=False,
    )
    outgoing_edges: Mapped[list[FlowEdgeModel]] = relationship(
        back_populates="provider_node",
        primaryjoin=lambda: and_(
            FlowNodeModel.flow_revision_id == FlowEdgeModel.flow_revision_id,
            FlowNodeModel.node_key == FlowEdgeModel.provider_node_key,
        ),
        foreign_keys="[FlowEdgeModel.flow_revision_id, FlowEdgeModel.provider_node_key]",
        lazy="raise",
        order_by="FlowEdgeModel.order_index",
        viewonly=True,
    )
    incoming_edges: Mapped[list[FlowEdgeModel]] = relationship(
        back_populates="consumer_node",
        primaryjoin=lambda: and_(
            FlowNodeModel.flow_revision_id == FlowEdgeModel.flow_revision_id,
            FlowNodeModel.node_key == FlowEdgeModel.consumer_node_key,
        ),
        foreign_keys="[FlowEdgeModel.flow_revision_id, FlowEdgeModel.consumer_node_key]",
        lazy="raise",
        order_by="FlowEdgeModel.order_index",
        viewonly=True,
    )


class FlowEdgeModel(RuntimeBase):
    __tablename__ = "flow_edges"
    __table_args__ = (
        UniqueConstraint("flow_revision_id", "consumer_node_key", "kind", "slot"),
        CheckConstraint(
            f"kind IN ({sql_in(FLOW_EDGE_KIND_VALUES)})",
            name="ck_flow_edges_kind",
        ),
        ForeignKeyConstraint(
            ["flow_revision_id", "provider_node_key"],
            ["flow_nodes.flow_revision_id", "flow_nodes.node_key"],
            name="fk_flow_edges_provider_node",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_revision_id", "consumer_node_key"],
            ["flow_nodes.flow_revision_id", "flow_nodes.node_key"],
            name="fk_flow_edges_consumer_node",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    flow_edge_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    flow_revision_id: Mapped[str] = mapped_column(ForeignKey("flow_revisions.flow_revision_id"))
    provider_node_key: Mapped[str] = mapped_column(String(255))
    consumer_node_key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    slot: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer)
    flow_revision: Mapped[FlowRevisionModel] = relationship(
        "FlowRevisionModel",
        back_populates="edges",
        foreign_keys=[flow_revision_id],
        lazy="raise",
    )
    provider_node: Mapped[FlowNodeModel] = relationship(
        back_populates="outgoing_edges",
        primaryjoin=lambda: and_(
            FlowEdgeModel.flow_revision_id == FlowNodeModel.flow_revision_id,
            FlowEdgeModel.provider_node_key == FlowNodeModel.node_key,
        ),
        foreign_keys=[flow_revision_id, provider_node_key],
        lazy="raise",
        viewonly=True,
    )
    consumer_node: Mapped[FlowNodeModel] = relationship(
        back_populates="incoming_edges",
        primaryjoin=lambda: and_(
            FlowEdgeModel.flow_revision_id == FlowNodeModel.flow_revision_id,
            FlowEdgeModel.consumer_node_key == FlowNodeModel.node_key,
        ),
        foreign_keys=[flow_revision_id, consumer_node_key],
        lazy="raise",
        viewonly=True,
    )


class NodePlanRevisionModel(RuntimeBase):
    __tablename__ = "node_plan_revisions"
    __table_args__ = (
        UniqueConstraint("flow_revision_id", "flow_node_id"),
        CheckConstraint(
            f"provider_kind IS NULL OR provider_kind IN ({sql_in(PROVIDER_VALUES)})",
            name="ck_node_plan_revisions_provider_kind",
        ),
        ForeignKeyConstraint(
            ["flow_id", "flow_revision_id", "flow_node_id"],
            ["flow_nodes.flow_id", "flow_nodes.flow_revision_id", "flow_nodes.flow_node_id"],
            name="fk_node_plan_revisions_flow_node_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["role_key", "role_revision_no"],
            ["role_revisions.role_key", "role_revisions.revision_no"],
            name="fk_node_plan_revisions_role_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["policy_key", "policy_revision_no"],
            ["policy_revisions.policy_key", "policy_revisions.revision_no"],
            name="fk_node_plan_revisions_policy_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    node_plan_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    flow_id: Mapped[str] = mapped_column(String(255))
    flow_revision_id: Mapped[str] = mapped_column(String(255))
    flow_node_id: Mapped[str] = mapped_column(String(255))
    role_key: Mapped[str] = mapped_column(String(255))
    role_revision_no: Mapped[int] = mapped_column(Integer)
    role_description: Mapped[str] = mapped_column(Text)
    role_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_key: Mapped[str] = mapped_column(String(255))
    policy_revision_no: Mapped[int] = mapped_column(Integer)
    policy_description: Mapped[str] = mapped_column(Text)
    policy_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flow_revision: Mapped[FlowRevisionModel] = relationship(
        "FlowRevisionModel",
        back_populates="node_plan_revisions",
        primaryjoin=(
            "and_(NodePlanRevisionModel.flow_id == FlowRevisionModel.flow_id, "
            "NodePlanRevisionModel.flow_revision_id == FlowRevisionModel.flow_revision_id)"
        ),
        foreign_keys=[flow_id, flow_revision_id],
        lazy="raise",
        viewonly=True,
    )
    flow_node: Mapped[FlowNodeModel] = relationship(
        back_populates="plan_revision",
        foreign_keys=[flow_id, flow_revision_id, flow_node_id],
        lazy="raise",
    )
    role_revision: Mapped[RoleRevisionModel] = relationship(
        "RoleRevisionModel",
        primaryjoin=lambda: and_(
            NodePlanRevisionModel.role_key == RoleRevisionModel.role_key,
            NodePlanRevisionModel.role_revision_no == RoleRevisionModel.revision_no,
        ),
        foreign_keys=[role_key, role_revision_no],
        lazy="raise",
        viewonly=True,
    )
    policy_revision: Mapped[PolicyRevisionModel] = relationship(
        "PolicyRevisionModel",
        primaryjoin=lambda: and_(
            NodePlanRevisionModel.policy_key == PolicyRevisionModel.policy_key,
            NodePlanRevisionModel.policy_revision_no == PolicyRevisionModel.revision_no,
        ),
        foreign_keys=[policy_key, policy_revision_no],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["FlowEdgeModel", "FlowNodeModel", "NodePlanRevisionModel"]

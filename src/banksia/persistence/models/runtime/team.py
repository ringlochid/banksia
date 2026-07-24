from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import utcnow

if TYPE_CHECKING:
    from banksia.persistence.models.registry import WorkflowRevisionModel
    from banksia.persistence.models.runtime.task import TaskModel


class MemberModel(RuntimeBase):
    __tablename__ = "members"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
    )
    member_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )


class MemberConfigurationModel(RuntimeBase):
    __tablename__ = "member_configurations"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "member_configuration_id",
            name="uq_member_configurations_task_configuration",
        ),
        UniqueConstraint(
            "task_id",
            "member_id",
            "member_configuration_id",
            name="uq_member_configurations_task_member_configuration",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id"],
            ["members.task_id", "members.member_id"],
            name="fk_member_configurations_member",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id", "predecessor_member_configuration_id"],
            [
                "member_configurations.task_id",
                "member_configurations.member_id",
                "member_configurations.member_configuration_id",
            ],
            name="fk_member_configurations_predecessor",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "predecessor_member_configuration_id IS NULL OR "
            "predecessor_member_configuration_id != member_configuration_id",
            name="ck_member_configurations_predecessor_not_self",
        ),
    )

    member_configuration_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), index=True)
    member_id: Mapped[str] = mapped_column(String(128), index=True)
    predecessor_member_configuration_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_provider_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    requested_capabilities_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    basis_kind: Mapped[str] = mapped_column(String(64))
    basis_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    member: Mapped[MemberModel] = relationship(
        "MemberModel",
        foreign_keys=[task_id, member_id],
        lazy="raise",
    )
    predecessor: Mapped[MemberConfigurationModel | None] = relationship(
        "MemberConfigurationModel",
        foreign_keys=[task_id, member_id, predecessor_member_configuration_id],
        remote_side=lambda: [
            MemberConfigurationModel.task_id,
            MemberConfigurationModel.member_id,
            MemberConfigurationModel.member_configuration_id,
        ],
        lazy="raise",
        viewonly=True,
    )


class MemberBranchBasisModel(RuntimeBase):
    __tablename__ = "member_branch_bases"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "member_id",
            "member_branch_basis_id",
            name="uq_member_branch_bases_task_member_basis",
        ),
        UniqueConstraint(
            "task_id",
            "member_id",
            "member_configuration_id",
            "member_branch_basis_id",
            name="uq_member_branch_bases_exact_configuration_basis",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id"],
            ["members.task_id", "members.member_id"],
            name="fk_member_branch_bases_member",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id", "member_configuration_id"],
            [
                "member_configurations.task_id",
                "member_configurations.member_id",
                "member_configurations.member_configuration_id",
            ],
            name="fk_member_branch_bases_configuration",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "parent_member_id", "parent_member_branch_basis_id"],
            [
                "member_branch_bases.task_id",
                "member_branch_bases.member_id",
                "member_branch_bases.member_branch_basis_id",
            ],
            name="fk_member_branch_bases_parent",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "(parent_member_id IS NULL AND parent_member_branch_basis_id IS NULL) OR "
            "(parent_member_id IS NOT NULL AND parent_member_branch_basis_id IS NOT NULL)",
            name="ck_member_branch_bases_parent_shape",
        ),
    )

    member_branch_basis_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), index=True)
    member_id: Mapped[str] = mapped_column(String(128), index=True)
    member_configuration_id: Mapped[str] = mapped_column(String(255))
    parent_member_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_member_branch_basis_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    member: Mapped[MemberModel] = relationship(
        "MemberModel",
        foreign_keys=[task_id, member_id],
        lazy="raise",
    )
    configuration: Mapped[MemberConfigurationModel] = relationship(
        "MemberConfigurationModel",
        foreign_keys=[task_id, member_id, member_configuration_id],
        lazy="raise",
        viewonly=True,
    )
    parent: Mapped[MemberBranchBasisModel | None] = relationship(
        "MemberBranchBasisModel",
        foreign_keys=[task_id, parent_member_id, parent_member_branch_basis_id],
        remote_side=lambda: [
            MemberBranchBasisModel.task_id,
            MemberBranchBasisModel.member_id,
            MemberBranchBasisModel.member_branch_basis_id,
        ],
        lazy="raise",
        viewonly=True,
    )


class TeamRevisionModel(RuntimeBase):
    __tablename__ = "team_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "team_revision_id", name="uq_team_revisions_task_revision"),
        UniqueConstraint("task_id", "revision_no", name="uq_team_revisions_task_number"),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "predecessor_team_revision_id",
            name="uq_team_revisions_exact_predecessor",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "workflow_key",
            "workflow_revision_no",
            "workflow_content_hash",
            name="uq_team_revisions_task_workflow_identity",
        ),
        ForeignKeyConstraint(
            ["task_id", "root_member_id"],
            ["members.task_id", "members.member_id"],
            name="fk_team_revisions_root_member",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "team_revision_id",
                "root_member_id",
                "root_selection_marker",
            ],
            [
                "team_revision_members.task_id",
                "team_revision_members.team_revision_id",
                "team_revision_members.member_id",
                "team_revision_members.root_selection_marker",
            ],
            name="fk_team_revisions_selected_root",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "predecessor_team_revision_id"],
            ["team_revisions.task_id", "team_revisions.team_revision_id"],
            name="fk_team_revisions_predecessor",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["workflow_key", "workflow_revision_no", "workflow_content_hash"],
            [
                "workflow_revisions.workflow_key",
                "workflow_revisions.revision_no",
                "workflow_revisions.content_hash",
            ],
            name="fk_team_revisions_workflow_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision_no >= 1", name="ck_team_revisions_revision_no"),
        CheckConstraint(
            "root_selection_marker = 1",
            name="ck_team_revisions_root_selection_marker",
        ),
        CheckConstraint(
            "predecessor_team_revision_id IS NULL OR "
            "predecessor_team_revision_id != team_revision_id",
            name="ck_team_revisions_predecessor_not_self",
        ),
    )

    team_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    predecessor_team_revision_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    root_member_id: Mapped[str] = mapped_column(String(128))
    root_selection_marker: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )
    workflow_key: Mapped[str] = mapped_column(String(255))
    workflow_revision_no: Mapped[int] = mapped_column(Integer)
    workflow_content_hash: Mapped[str] = mapped_column(String(64))
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    root_member: Mapped[MemberModel] = relationship(
        "MemberModel",
        foreign_keys=[task_id, root_member_id],
        lazy="raise",
        viewonly=True,
    )
    root_selection: Mapped[TeamRevisionMemberModel] = relationship(
        "TeamRevisionMemberModel",
        foreign_keys=[
            task_id,
            team_revision_id,
            root_member_id,
            root_selection_marker,
        ],
        lazy="raise",
        viewonly=True,
    )
    predecessor: Mapped[TeamRevisionModel | None] = relationship(
        "TeamRevisionModel",
        foreign_keys=[task_id, predecessor_team_revision_id],
        remote_side=lambda: [TeamRevisionModel.task_id, TeamRevisionModel.team_revision_id],
        lazy="raise",
        viewonly=True,
    )
    workflow_revision: Mapped[WorkflowRevisionModel] = relationship(
        "WorkflowRevisionModel",
        foreign_keys=[workflow_key, workflow_revision_no, workflow_content_hash],
        lazy="raise",
        viewonly=True,
    )


class TeamRevisionMemberModel(RuntimeBase):
    __tablename__ = "team_revision_members"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "preorder_index",
            name="uq_team_revision_members_preorder",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "parent_member_id",
            "sibling_order",
            name="uq_team_revision_members_sibling_order",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "member_id",
            "member_configuration_id",
            "member_branch_basis_id",
            name="uq_team_revision_members_exact_selection",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "member_id",
            "parent_member_id",
            "member_configuration_id",
            "member_branch_basis_id",
            name="uq_team_revision_members_exact_branch_selection",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "member_id",
            "root_selection_marker",
            name="uq_team_revision_members_exact_root_selection",
        ),
        UniqueConstraint(
            "task_id",
            "team_revision_id",
            "root_selection_marker",
            name="uq_team_revision_members_one_root",
        ),
        ForeignKeyConstraint(
            ["task_id", "team_revision_id"],
            ["team_revisions.task_id", "team_revisions.team_revision_id"],
            name="fk_team_revision_members_team_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id"],
            ["members.task_id", "members.member_id"],
            name="fk_team_revision_members_member",
        ),
        ForeignKeyConstraint(
            ["task_id", "member_id", "member_configuration_id"],
            [
                "member_configurations.task_id",
                "member_configurations.member_id",
                "member_configurations.member_configuration_id",
            ],
            name="fk_team_revision_members_configuration",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "member_id",
                "member_configuration_id",
                "member_branch_basis_id",
            ],
            [
                "member_branch_bases.task_id",
                "member_branch_bases.member_id",
                "member_branch_bases.member_configuration_id",
                "member_branch_bases.member_branch_basis_id",
            ],
            name="fk_team_revision_members_branch_basis",
        ),
        ForeignKeyConstraint(
            ["task_id", "team_revision_id", "parent_member_id"],
            [
                "team_revision_members.task_id",
                "team_revision_members.team_revision_id",
                "team_revision_members.member_id",
            ],
            name="fk_team_revision_members_parent",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("preorder_index >= 0", name="ck_team_revision_members_preorder"),
        CheckConstraint("sibling_order >= 0", name="ck_team_revision_members_sibling_order"),
        CheckConstraint(
            "parent_member_id IS NULL OR parent_member_id != member_id",
            name="ck_team_revision_members_parent_not_self",
        ),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    team_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    parent_member_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    root_selection_marker: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN parent_member_id IS NULL THEN 1 ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    member_configuration_id: Mapped[str] = mapped_column(String(255))
    member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    preorder_index: Mapped[int] = mapped_column(Integer)
    sibling_order: Mapped[int] = mapped_column(Integer)
    team_revision: Mapped[TeamRevisionModel] = relationship(
        "TeamRevisionModel",
        foreign_keys=[task_id, team_revision_id],
        lazy="raise",
    )
    member: Mapped[MemberModel] = relationship(
        "MemberModel",
        foreign_keys=[task_id, member_id],
        lazy="raise",
        viewonly=True,
    )
    configuration: Mapped[MemberConfigurationModel] = relationship(
        "MemberConfigurationModel",
        foreign_keys=[task_id, member_id, member_configuration_id],
        lazy="raise",
        viewonly=True,
    )
    branch_basis: Mapped[MemberBranchBasisModel] = relationship(
        "MemberBranchBasisModel",
        foreign_keys=[
            task_id,
            member_id,
            member_configuration_id,
            member_branch_basis_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    parent: Mapped[TeamRevisionMemberModel | None] = relationship(
        "TeamRevisionMemberModel",
        foreign_keys=[task_id, team_revision_id, parent_member_id],
        remote_side=lambda: [
            TeamRevisionMemberModel.task_id,
            TeamRevisionMemberModel.team_revision_id,
            TeamRevisionMemberModel.member_id,
        ],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "MemberBranchBasisModel",
    "MemberConfigurationModel",
    "MemberModel",
    "TeamRevisionMemberModel",
    "TeamRevisionModel",
]

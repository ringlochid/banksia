from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

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
from autoclaw.persistence.datetimes import UtcDateTime

utcnow = partial(datetime.now, tz=UTC)


class WorkflowDefinitionModel(RuntimeBase):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        CheckConstraint(
            "current_revision_no IS NULL OR current_revision_no >= 1",
            name="ck_workflow_definitions_revision_no",
        ),
        ForeignKeyConstraint(
            ["workflow_key", "current_revision_no"],
            ["workflow_revisions.workflow_key", "workflow_revisions.revision_no"],
            name="fk_workflow_definitions_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    workflow_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    current_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    revisions: Mapped[list[WorkflowRevisionModel]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        foreign_keys="WorkflowRevisionModel.workflow_key",
    )
    current_revision: Mapped[WorkflowRevisionModel | None] = relationship(
        primaryjoin=lambda: and_(
            WorkflowDefinitionModel.workflow_key == WorkflowRevisionModel.workflow_key,
            WorkflowDefinitionModel.current_revision_no == WorkflowRevisionModel.revision_no,
        ),
        foreign_keys=lambda: [
            WorkflowDefinitionModel.workflow_key,
            WorkflowDefinitionModel.current_revision_no,
        ],
        uselist=False,
        viewonly=True,
    )


class WorkflowRevisionModel(RuntimeBase):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_key", "revision_no"),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_workflow_revisions_revision_no",
        ),
    )

    workflow_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.workflow_key"))
    revision_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    definition: Mapped[WorkflowDefinitionModel] = relationship(
        back_populates="revisions",
        foreign_keys=[workflow_key],
    )


class RoleDefinitionModel(RuntimeBase):
    __tablename__ = "role_definitions"
    __table_args__ = (
        CheckConstraint(
            "current_revision_no IS NULL OR current_revision_no >= 1",
            name="ck_role_definitions_revision_no",
        ),
        ForeignKeyConstraint(
            ["role_key", "current_revision_no"],
            ["role_revisions.role_key", "role_revisions.revision_no"],
            name="fk_role_definitions_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    role_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    current_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    revisions: Mapped[list[RoleRevisionModel]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        foreign_keys="RoleRevisionModel.role_key",
    )
    current_revision: Mapped[RoleRevisionModel | None] = relationship(
        primaryjoin=lambda: and_(
            RoleDefinitionModel.role_key == RoleRevisionModel.role_key,
            RoleDefinitionModel.current_revision_no == RoleRevisionModel.revision_no,
        ),
        foreign_keys=lambda: [
            RoleDefinitionModel.role_key,
            RoleDefinitionModel.current_revision_no,
        ],
        uselist=False,
        viewonly=True,
    )


class RoleRevisionModel(RuntimeBase):
    __tablename__ = "role_revisions"
    __table_args__ = (
        UniqueConstraint("role_key", "revision_no"),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_role_revisions_revision_no",
        ),
    )

    role_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role_key: Mapped[str] = mapped_column(ForeignKey("role_definitions.role_key"))
    revision_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    definition: Mapped[RoleDefinitionModel] = relationship(
        back_populates="revisions",
        foreign_keys=[role_key],
    )


class PolicyDefinitionModel(RuntimeBase):
    __tablename__ = "policy_definitions"
    __table_args__ = (
        CheckConstraint(
            "current_revision_no IS NULL OR current_revision_no >= 1",
            name="ck_policy_definitions_revision_no",
        ),
        ForeignKeyConstraint(
            ["policy_key", "current_revision_no"],
            ["policy_revisions.policy_key", "policy_revisions.revision_no"],
            name="fk_policy_definitions_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    policy_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    current_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    revisions: Mapped[list[PolicyRevisionModel]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        foreign_keys="PolicyRevisionModel.policy_key",
    )
    current_revision: Mapped[PolicyRevisionModel | None] = relationship(
        primaryjoin=lambda: and_(
            PolicyDefinitionModel.policy_key == PolicyRevisionModel.policy_key,
            PolicyDefinitionModel.current_revision_no == PolicyRevisionModel.revision_no,
        ),
        foreign_keys=lambda: [
            PolicyDefinitionModel.policy_key,
            PolicyDefinitionModel.current_revision_no,
        ],
        uselist=False,
        viewonly=True,
    )


class PolicyRevisionModel(RuntimeBase):
    __tablename__ = "policy_revisions"
    __table_args__ = (
        UniqueConstraint("policy_key", "revision_no"),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_policy_revisions_revision_no",
        ),
    )

    policy_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    policy_key: Mapped[str] = mapped_column(ForeignKey("policy_definitions.policy_key"))
    revision_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    definition: Mapped[PolicyDefinitionModel] = relationship(
        back_populates="revisions",
        foreign_keys=[policy_key],
    )

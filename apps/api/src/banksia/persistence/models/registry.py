from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from sqlalchemy import (
    JSON,
    Boolean,
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

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime

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
        UniqueConstraint(
            "workflow_key",
            "revision_no",
            "content_hash",
            name="uq_workflow_revisions_key_revision_hash",
        ),
        CheckConstraint(
            "revision_no >= 1",
            name="ck_workflow_revisions_revision_no",
        ),
        CheckConstraint(
            "provenance IN ('starter_seed', 'user')",
            name="ck_workflow_revisions_provenance",
        ),
        UniqueConstraint(
            "workflow_key",
            "content_hash",
            "provenance",
            name="uq_workflow_revisions_content_provenance",
        ),
    )

    workflow_revision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.workflow_key"))
    revision_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    provenance: Mapped[str] = mapped_column(String(32))
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    definition: Mapped[WorkflowDefinitionModel] = relationship(
        back_populates="revisions",
        foreign_keys=[workflow_key],
    )


class WorkflowDraftModel(RuntimeBase):
    __tablename__ = "workflow_drafts"
    __table_args__ = (
        CheckConstraint(
            "base_revision_no IS NULL OR base_revision_no >= 1",
            name="ck_workflow_drafts_base_revision_no",
        ),
        CheckConstraint(
            "next_member_sequence >= 1",
            name="ck_workflow_drafts_next_member_sequence",
        ),
        ForeignKeyConstraint(
            ["workflow_key", "base_revision_no"],
            ["workflow_revisions.workflow_key", "workflow_revisions.revision_no"],
            name="fk_workflow_drafts_base_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("workflow_key", name="uq_workflow_drafts_workflow_key"),
        UniqueConstraint("etag", name="uq_workflow_drafts_etag"),
    )

    draft_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(String(128))
    base_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    etag: Mapped[str] = mapped_column(String(255))
    next_member_sequence: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(),
        default=utcnow,
        onupdate=utcnow,
    )
    base_revision: Mapped[WorkflowRevisionModel | None] = relationship(
        primaryjoin=lambda: and_(
            WorkflowDraftModel.workflow_key == WorkflowRevisionModel.workflow_key,
            WorkflowDraftModel.base_revision_no == WorkflowRevisionModel.revision_no,
        ),
        foreign_keys=lambda: [
            WorkflowDraftModel.workflow_key,
            WorkflowDraftModel.base_revision_no,
        ],
        uselist=False,
        viewonly=True,
        lazy="raise",
    )
    undo_receipts: Mapped[list[WorkflowUndoReceiptModel]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class WorkflowUndoReceiptModel(RuntimeBase):
    __tablename__ = "workflow_undo_receipts"
    __table_args__ = (
        UniqueConstraint("expected_etag", name="uq_workflow_undo_receipts_expected_etag"),
    )

    receipt_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_drafts.draft_id", ondelete="CASCADE")
    )
    expected_etag: Mapped[str] = mapped_column(String(255))
    previous_content_hash: Mapped[str] = mapped_column(String(64))
    previous_content_json: Mapped[dict[str, object]] = mapped_column(JSON(none_as_null=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    draft: Mapped[WorkflowDraftModel] = relationship(
        back_populates="undo_receipts",
        lazy="raise",
    )

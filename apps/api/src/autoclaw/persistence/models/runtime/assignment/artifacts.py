from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.datetimes import UtcDateTime
from autoclaw.persistence.models.runtime.common import (
    TRANSIENT_RETENTION_STATUS_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.assignment.execution import (
        AttemptCheckpointModel,
        AttemptModel,
    )


class ArtifactPublicationModel(RuntimeBase):
    __tablename__ = "artifact_publications"
    __table_args__ = (
        UniqueConstraint("task_id", "assignment_id", "slot", "version"),
        UniqueConstraint(
            "artifact_publication_id",
            "task_id",
            "flow_id",
            "assignment_id",
            "attempt_id",
            "checkpoint_id",
            "slot",
            "version",
        ),
        UniqueConstraint(
            "artifact_publication_id",
            "task_id",
            "flow_id",
            "assignment_id",
            "slot",
            "version",
        ),
        CheckConstraint("version >= 1", name="ck_artifact_publications_version"),
        CheckConstraint(
            "(supersedes_publication_id IS NULL AND supersedes_version IS NULL) OR "
            "(supersedes_publication_id IS NOT NULL AND supersedes_version IS NOT NULL "
            "AND supersedes_version < version)",
            name="ck_artifact_publications_supersedes_pair",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id", "attempt_id", "checkpoint_id"],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.flow_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_artifact_publications_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "supersedes_publication_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "slot",
                "supersedes_version",
            ],
            [
                "artifact_publications.artifact_publication_id",
                "artifact_publications.task_id",
                "artifact_publications.flow_id",
                "artifact_publications.assignment_id",
                "artifact_publications.slot",
                "artifact_publications.version",
            ],
            name="fk_artifact_publications_supersedes",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_artifact_publications_lookup", "task_id", "assignment_id", "slot"),
    )

    artifact_publication_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255))
    checkpoint_id: Mapped[str] = mapped_column(String(255))
    slot: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer)
    logical_path: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    supersedes_publication_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supersedes_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    checkpoint: Mapped[AttemptCheckpointModel] = relationship(
        "AttemptCheckpointModel",
        back_populates="artifact_publications",
        foreign_keys=[task_id, flow_id, assignment_id, attempt_id, checkpoint_id],
        lazy="raise",
        viewonly=True,
    )
    supersedes_publication: Mapped[ArtifactPublicationModel | None] = relationship(
        remote_side=lambda: [
            ArtifactPublicationModel.artifact_publication_id,
            ArtifactPublicationModel.task_id,
            ArtifactPublicationModel.flow_id,
            ArtifactPublicationModel.assignment_id,
            ArtifactPublicationModel.slot,
            ArtifactPublicationModel.version,
        ],
        foreign_keys=[
            supersedes_publication_id,
            task_id,
            flow_id,
            assignment_id,
            slot,
            supersedes_version,
        ],
        lazy="raise",
        viewonly=True,
    )


class ArtifactCurrentPointerModel(RuntimeBase):
    __tablename__ = "artifact_current_pointers"
    __table_args__ = (
        UniqueConstraint("task_id", "assignment_id", "slot"),
        ForeignKeyConstraint(
            [
                "current_publication_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "checkpoint_id",
                "slot",
                "current_version",
            ],
            [
                "artifact_publications.artifact_publication_id",
                "artifact_publications.task_id",
                "artifact_publications.flow_id",
                "artifact_publications.assignment_id",
                "artifact_publications.attempt_id",
                "artifact_publications.checkpoint_id",
                "artifact_publications.slot",
                "artifact_publications.version",
            ],
            name="fk_artifact_current_pointers_publication",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    artifact_current_pointer_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    slot: Mapped[str] = mapped_column(String(255))
    current_publication_id: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(255))
    checkpoint_id: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    current_publication: Mapped[ArtifactPublicationModel] = relationship(
        "ArtifactPublicationModel",
        foreign_keys=[
            current_publication_id,
            task_id,
            flow_id,
            assignment_id,
            attempt_id,
            checkpoint_id,
            slot,
            current_version,
        ],
        lazy="raise",
        viewonly=True,
    )


class TransientLocalizationModel(RuntimeBase):
    __tablename__ = "transient_localizations"
    __table_args__ = (
        UniqueConstraint(
            "transient_localization_id",
            "task_id",
            "assignment_id",
            "attempt_id",
        ),
        CheckConstraint(
            f"retention_status IN ({sql_in(TRANSIENT_RETENTION_STATUS_VALUES)})",
            name="ck_transient_localizations_retention_status",
        ),
        CheckConstraint(
            "(retention_status = 'active' AND removed_at IS NULL) OR "
            "(retention_status = 'expired' AND expires_at IS NOT NULL "
            "AND removed_at IS NULL) OR "
            "(retention_status = 'removed' AND expires_at IS NOT NULL "
            "AND removed_at IS NOT NULL)",
            name="ck_transient_localizations_retention_time",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "attempts.task_id",
                "attempts.flow_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
            ],
            name="fk_transient_localizations_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id", "checkpoint_id"],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_transient_localizations_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_transient_localizations_retention",
            "retention_status",
            "transient_localization_id",
            "expires_at",
        ),
    )

    transient_localization_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"))
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255))
    checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_logical_path: Mapped[str] = mapped_column(Text)
    localized_logical_path: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    retention_status: Mapped[str] = mapped_column(String(64), default="active")
    localized_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    checkpoint: Mapped[AttemptCheckpointModel | None] = relationship(
        "AttemptCheckpointModel",
        back_populates="transient_localizations",
        foreign_keys=[task_id, assignment_id, attempt_id, checkpoint_id],
        lazy="raise",
        viewonly=True,
    )
    attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        foreign_keys=[task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )


class CheckpointTransientModel(RuntimeBase):
    __tablename__ = "checkpoint_transients"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "transient_localization_id"),
        UniqueConstraint("checkpoint_id", "order_index"),
        CheckConstraint("order_index >= 0", name="ck_checkpoint_transients_order_index"),
        ForeignKeyConstraint(
            ["task_id", "assignment_id", "attempt_id", "checkpoint_id"],
            [
                "attempt_checkpoints.task_id",
                "attempt_checkpoints.assignment_id",
                "attempt_checkpoints.attempt_id",
                "attempt_checkpoints.checkpoint_id",
            ],
            name="fk_checkpoint_transients_checkpoint_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["transient_localization_id", "task_id", "assignment_id", "attempt_id"],
            [
                "transient_localizations.transient_localization_id",
                "transient_localizations.task_id",
                "transient_localizations.assignment_id",
                "transient_localizations.attempt_id",
            ],
            name="fk_checkpoint_transients_transient_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    checkpoint_transient_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    assignment_id: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255))
    checkpoint_id: Mapped[str] = mapped_column(String(255))
    transient_localization_id: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer)
    checkpoint: Mapped[AttemptCheckpointModel] = relationship(
        "AttemptCheckpointModel",
        back_populates="checkpoint_transients",
        foreign_keys=[task_id, assignment_id, attempt_id, checkpoint_id],
        lazy="raise",
        viewonly=True,
    )
    transient_localization: Mapped[TransientLocalizationModel] = relationship(
        "TransientLocalizationModel",
        foreign_keys=[transient_localization_id, task_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "ArtifactCurrentPointerModel",
    "ArtifactPublicationModel",
    "CheckpointTransientModel",
    "TransientLocalizationModel",
]

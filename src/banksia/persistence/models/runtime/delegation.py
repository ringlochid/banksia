from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import sql_in, utcnow

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import AssignmentModel
    from banksia.persistence.models.runtime.dispatch.support import AcceptedBoundaryModel
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.team import TeamRevisionMemberModel

DELEGATION_WAVE_STATUS_VALUES = ("open", "settled", "cancelled")
DELEGATION_WAVE_MEMBER_STATUS_VALUES = ("pending", "settled", "cancelled")


class DelegationWaveModel(RuntimeBase):
    """One exact parent Dispatch fan-out/fan-in source."""

    __tablename__ = "delegation_waves"
    __table_args__ = (
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("successor_dispatch_id"),
        UniqueConstraint(
            "delegation_wave_id",
            "task_id",
            "parent_assignment_id",
            "parent_attempt_id",
            "source_dispatch_id",
            name="uq_delegation_waves_complete_owner",
        ),
        UniqueConstraint(
            "delegation_wave_id",
            "task_id",
            "parent_assignment_id",
            "parent_attempt_id",
            "source_dispatch_id",
            "team_revision_id",
            "parent_member_id",
            "parent_member_configuration_id",
            "parent_member_branch_basis_id",
            name="uq_delegation_waves_structural_owner",
        ),
        CheckConstraint(
            f"status IN ({sql_in(DELEGATION_WAVE_STATUS_VALUES)})",
            name="ck_delegation_waves_status",
        ),
        CheckConstraint(
            "(status = 'open' AND settled_at IS NULL AND cancelled_at IS NULL AND "
            "successor_dispatch_id IS NULL) OR "
            "(status = 'settled' AND settled_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND "
            "successor_dispatch_id IS NULL)",
            name="ck_delegation_waves_lifecycle",
        ),
        ForeignKeyConstraint(
            [
                "source_dispatch_id",
                "task_id",
                "parent_assignment_id",
                "parent_attempt_id",
                "team_revision_id",
                "parent_member_id",
                "parent_member_configuration_id",
                "parent_member_branch_basis_id",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
                "dispatch_turns.team_revision_id",
                "dispatch_turns.member_id",
                "dispatch_turns.member_configuration_id",
                "dispatch_turns.member_branch_basis_id",
            ],
            name="fk_delegation_waves_source_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "parent_assignment_id", "parent_attempt_id"],
            ["attempts.task_id", "attempts.assignment_id", "attempts.attempt_id"],
            name="fk_delegation_waves_parent_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "successor_dispatch_id",
                "task_id",
                "parent_assignment_id",
                "parent_attempt_id",
                "source_dispatch_id",
            ],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
                "dispatch_turns.predecessor_dispatch_id",
            ],
            name="fk_delegation_waves_exact_successor_lineage",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_delegation_waves_status", "status"),
    )

    delegation_wave_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    parent_assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    parent_attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    team_revision_id: Mapped[str] = mapped_column(String(255))
    parent_member_id: Mapped[str] = mapped_column(String(128))
    parent_member_configuration_id: Mapped[str] = mapped_column(String(255))
    parent_member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(64), default="open", server_default="open")
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        foreign_keys=[
            source_dispatch_id,
            task_id,
            parent_assignment_id,
            parent_attempt_id,
            team_revision_id,
            parent_member_id,
            parent_member_configuration_id,
            parent_member_branch_basis_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[
            successor_dispatch_id,
            task_id,
            parent_assignment_id,
            parent_attempt_id,
            source_dispatch_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    members: Mapped[list[DelegationWaveMemberModel]] = relationship(
        back_populates="wave",
        primaryjoin=(
            "and_(DelegationWaveModel.delegation_wave_id == "
            "DelegationWaveMemberModel.delegation_wave_id, "
            "DelegationWaveModel.task_id == DelegationWaveMemberModel.task_id, "
            "DelegationWaveModel.parent_assignment_id == "
            "DelegationWaveMemberModel.parent_assignment_id, "
            "DelegationWaveModel.parent_attempt_id == "
            "DelegationWaveMemberModel.parent_attempt_id, "
            "DelegationWaveModel.source_dispatch_id == "
            "DelegationWaveMemberModel.source_dispatch_id, "
            "DelegationWaveModel.team_revision_id == "
            "DelegationWaveMemberModel.team_revision_id, "
            "DelegationWaveModel.parent_member_id == "
            "DelegationWaveMemberModel.parent_member_id, "
            "DelegationWaveModel.parent_member_configuration_id == "
            "DelegationWaveMemberModel.parent_member_configuration_id, "
            "DelegationWaveModel.parent_member_branch_basis_id == "
            "DelegationWaveMemberModel.parent_member_branch_basis_id)"
        ),
        foreign_keys=(
            "[DelegationWaveMemberModel.delegation_wave_id, "
            "DelegationWaveMemberModel.task_id, "
            "DelegationWaveMemberModel.parent_assignment_id, "
            "DelegationWaveMemberModel.parent_attempt_id, "
            "DelegationWaveMemberModel.source_dispatch_id, "
            "DelegationWaveMemberModel.team_revision_id, "
            "DelegationWaveMemberModel.parent_member_id, "
            "DelegationWaveMemberModel.parent_member_configuration_id, "
            "DelegationWaveMemberModel.parent_member_branch_basis_id]"
        ),
        lazy="raise",
        order_by="DelegationWaveMemberModel.order_index",
    )


class DelegationWaveMemberModel(RuntimeBase):
    """One ordered child Assignment and exact direct-child team selection."""

    __tablename__ = "delegation_wave_members"
    __table_args__ = (
        PrimaryKeyConstraint("delegation_wave_id", "order_index"),
        UniqueConstraint("child_assignment_id"),
        UniqueConstraint("terminal_boundary_id"),
        CheckConstraint("order_index >= 0", name="ck_delegation_wave_members_order"),
        CheckConstraint(
            f"status IN ({sql_in(DELEGATION_WAVE_MEMBER_STATUS_VALUES)})",
            name="ck_delegation_wave_members_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND terminal_boundary_id IS NULL AND "
            "terminal_outcome IS NULL AND settled_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'settled' AND terminal_boundary_id IS NOT NULL AND "
            "terminal_outcome IN ('green', 'blocked') AND settled_at IS NOT NULL AND "
            "cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND terminal_boundary_id IS NULL AND "
            "terminal_outcome IS NULL AND settled_at IS NULL AND cancelled_at IS NOT NULL)",
            name="ck_delegation_wave_members_lifecycle",
        ),
        ForeignKeyConstraint(
            [
                "delegation_wave_id",
                "task_id",
                "parent_assignment_id",
                "parent_attempt_id",
                "source_dispatch_id",
                "team_revision_id",
                "parent_member_id",
                "parent_member_configuration_id",
                "parent_member_branch_basis_id",
            ],
            [
                "delegation_waves.delegation_wave_id",
                "delegation_waves.task_id",
                "delegation_waves.parent_assignment_id",
                "delegation_waves.parent_attempt_id",
                "delegation_waves.source_dispatch_id",
                "delegation_waves.team_revision_id",
                "delegation_waves.parent_member_id",
                "delegation_waves.parent_member_configuration_id",
                "delegation_waves.parent_member_branch_basis_id",
            ],
            name="fk_delegation_wave_members_wave_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["child_assignment_id", "parent_assignment_id", "source_dispatch_id"],
            [
                "assignments.assignment_id",
                "assignments.parent_assignment_id",
                "assignments.created_by_dispatch_id",
            ],
            name="fk_delegation_wave_members_child_source",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["task_id", "child_assignment_id", "child_member_id"],
            ["assignments.task_id", "assignments.assignment_id", "assignments.member_id"],
            name="fk_delegation_wave_members_child_member",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "task_id",
                "team_revision_id",
                "child_member_id",
                "parent_member_id",
                "child_member_configuration_id",
                "child_member_branch_basis_id",
            ],
            [
                "team_revision_members.task_id",
                "team_revision_members.team_revision_id",
                "team_revision_members.member_id",
                "team_revision_members.parent_member_id",
                "team_revision_members.member_configuration_id",
                "team_revision_members.member_branch_basis_id",
            ],
            name="fk_delegation_wave_members_direct_child",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "terminal_boundary_id",
                "task_id",
                "child_assignment_id",
                "terminal_outcome",
            ],
            [
                "accepted_boundaries.accepted_boundary_id",
                "accepted_boundaries.task_id",
                "accepted_boundaries.assignment_id",
                "accepted_boundaries.outcome",
            ],
            name="fk_delegation_wave_members_terminal_boundary_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    delegation_wave_id: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    parent_assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    parent_attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    team_revision_id: Mapped[str] = mapped_column(String(255))
    parent_member_id: Mapped[str] = mapped_column(String(128))
    parent_member_configuration_id: Mapped[str] = mapped_column(String(255))
    parent_member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    child_assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    child_member_id: Mapped[str] = mapped_column(String(128))
    child_member_configuration_id: Mapped[str] = mapped_column(String(255))
    child_member_branch_basis_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(64), default="pending", server_default="pending")
    terminal_boundary_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    terminal_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    wave: Mapped[DelegationWaveModel] = relationship(
        back_populates="members",
        primaryjoin=(
            "and_(DelegationWaveMemberModel.delegation_wave_id == "
            "DelegationWaveModel.delegation_wave_id, "
            "DelegationWaveMemberModel.task_id == DelegationWaveModel.task_id, "
            "DelegationWaveMemberModel.parent_assignment_id == "
            "DelegationWaveModel.parent_assignment_id, "
            "DelegationWaveMemberModel.parent_attempt_id == "
            "DelegationWaveModel.parent_attempt_id, "
            "DelegationWaveMemberModel.source_dispatch_id == "
            "DelegationWaveModel.source_dispatch_id, "
            "DelegationWaveMemberModel.team_revision_id == "
            "DelegationWaveModel.team_revision_id, "
            "DelegationWaveMemberModel.parent_member_id == "
            "DelegationWaveModel.parent_member_id, "
            "DelegationWaveMemberModel.parent_member_configuration_id == "
            "DelegationWaveModel.parent_member_configuration_id, "
            "DelegationWaveMemberModel.parent_member_branch_basis_id == "
            "DelegationWaveModel.parent_member_branch_basis_id)"
        ),
        foreign_keys=[
            delegation_wave_id,
            task_id,
            parent_assignment_id,
            parent_attempt_id,
            source_dispatch_id,
            team_revision_id,
            parent_member_id,
            parent_member_configuration_id,
            parent_member_branch_basis_id,
        ],
        lazy="raise",
    )
    child_assignment: Mapped[AssignmentModel] = relationship(
        "AssignmentModel",
        primaryjoin=(
            "and_(DelegationWaveMemberModel.child_assignment_id == "
            "AssignmentModel.assignment_id, "
            "DelegationWaveMemberModel.task_id == AssignmentModel.task_id, "
            "DelegationWaveMemberModel.parent_assignment_id == "
            "AssignmentModel.parent_assignment_id, "
            "DelegationWaveMemberModel.source_dispatch_id == "
            "AssignmentModel.created_by_dispatch_id, "
            "DelegationWaveMemberModel.child_member_id == AssignmentModel.member_id)"
        ),
        foreign_keys=[
            child_assignment_id,
            child_member_id,
            parent_assignment_id,
            source_dispatch_id,
            task_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    child_team_selection: Mapped[TeamRevisionMemberModel] = relationship(
        "TeamRevisionMemberModel",
        foreign_keys=[
            task_id,
            team_revision_id,
            child_member_id,
            parent_member_id,
            child_member_configuration_id,
            child_member_branch_basis_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    terminal_boundary: Mapped[AcceptedBoundaryModel | None] = relationship(
        "AcceptedBoundaryModel",
        foreign_keys=[
            terminal_boundary_id,
            task_id,
            child_assignment_id,
            terminal_outcome,
        ],
        lazy="raise",
        viewonly=True,
    )


__all__ = [
    "DELEGATION_WAVE_MEMBER_STATUS_VALUES",
    "DELEGATION_WAVE_STATUS_VALUES",
    "DelegationWaveMemberModel",
    "DelegationWaveModel",
]

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import utcnow

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.assignment.execution import (
        AttemptModel,
    )
    from banksia.persistence.models.runtime.command_runs import CommandRunModel
    from banksia.persistence.models.runtime.delegation import DelegationWaveModel
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from banksia.persistence.models.runtime.human_requests import HumanRequestModel


class AttemptWaitModel(RuntimeBase):
    """One exact typed suspension source selected by its owning Attempt."""

    __tablename__ = "attempt_waits"
    __table_args__ = (
        UniqueConstraint("attempt_id"),
        UniqueConstraint("source_dispatch_id"),
        UniqueConstraint("delegation_wave_id"),
        UniqueConstraint("human_request_id"),
        UniqueConstraint("command_run_id"),
        UniqueConstraint(
            "wait_id",
            "task_id",
            "flow_id",
            "assignment_id",
            "attempt_id",
            name="uq_attempt_waits_complete_owner",
        ),
        CheckConstraint(
            "(delegation_wave_id IS NOT NULL AND "
            "human_request_id IS NULL AND command_run_id IS NULL) OR "
            "(delegation_wave_id IS NULL AND "
            "human_request_id IS NOT NULL AND command_run_id IS NULL) OR "
            "(delegation_wave_id IS NULL AND "
            "human_request_id IS NULL AND command_run_id IS NOT NULL)",
            name="ck_attempt_waits_exactly_one_source",
        ),
        ForeignKeyConstraint(
            ["task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "attempts.task_id",
                "attempts.flow_id",
                "attempts.assignment_id",
                "attempts.attempt_id",
            ],
            name="fk_attempt_waits_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_dispatch_id", "task_id", "flow_id", "assignment_id", "attempt_id"],
            [
                "dispatch_turns.dispatch_id",
                "dispatch_turns.task_id",
                "dispatch_turns.flow_id",
                "dispatch_turns.assignment_id",
                "dispatch_turns.attempt_id",
            ],
            name="fk_attempt_waits_source_dispatch_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "wait_id"],
            ["attempts.attempt_id", "attempts.current_wait_id"],
            name="fk_attempt_waits_current_attempt_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "human_request_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "source_dispatch_id",
            ],
            [
                "human_requests.request_id",
                "human_requests.task_id",
                "human_requests.flow_id",
                "human_requests.assignment_id",
                "human_requests.attempt_id",
                "human_requests.source_dispatch_id",
            ],
            name="fk_attempt_waits_human_request_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "command_run_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "source_dispatch_id",
            ],
            [
                "command_runs.run_id",
                "command_runs.task_id",
                "command_runs.flow_id",
                "command_runs.assignment_id",
                "command_runs.attempt_id",
                "command_runs.source_dispatch_id",
            ],
            name="fk_attempt_waits_command_run_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            [
                "delegation_wave_id",
                "task_id",
                "flow_id",
                "assignment_id",
                "attempt_id",
                "source_dispatch_id",
            ],
            [
                "delegation_waves.delegation_wave_id",
                "delegation_waves.task_id",
                "delegation_waves.flow_id",
                "delegation_waves.parent_assignment_id",
                "delegation_waves.parent_attempt_id",
                "delegation_waves.source_dispatch_id",
            ],
            name="fk_attempt_waits_delegation_wave_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    wait_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), index=True)
    assignment_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt_id: Mapped[str] = mapped_column(String(255), index=True)
    source_dispatch_id: Mapped[str] = mapped_column(String(255), index=True)
    delegation_wave_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    human_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    command_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    attempt: Mapped[AttemptModel] = relationship(
        "AttemptModel",
        primaryjoin=(
            "and_(AttemptWaitModel.task_id == AttemptModel.task_id, "
            "AttemptWaitModel.flow_id == AttemptModel.flow_id, "
            "AttemptWaitModel.assignment_id == AttemptModel.assignment_id, "
            "AttemptWaitModel.attempt_id == AttemptModel.attempt_id, "
            "AttemptWaitModel.wait_id == AttemptModel.current_wait_id)"
        ),
        foreign_keys=[task_id, flow_id, assignment_id, attempt_id, wait_id],
        lazy="raise",
        viewonly=True,
    )
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="attempt_wait",
        foreign_keys=[source_dispatch_id, task_id, flow_id, assignment_id, attempt_id],
        lazy="raise",
        viewonly=True,
    )
    delegation_wave: Mapped[DelegationWaveModel | None] = relationship(
        "DelegationWaveModel",
        foreign_keys=[
            delegation_wave_id,
            task_id,
            flow_id,
            assignment_id,
            attempt_id,
            source_dispatch_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    human_request: Mapped[HumanRequestModel | None] = relationship(
        "HumanRequestModel",
        back_populates="attempt_wait",
        foreign_keys=[
            human_request_id,
            task_id,
            flow_id,
            assignment_id,
            attempt_id,
            source_dispatch_id,
        ],
        lazy="raise",
        viewonly=True,
    )
    command_run: Mapped[CommandRunModel | None] = relationship(
        "CommandRunModel",
        back_populates="attempt_wait",
        foreign_keys=[
            command_run_id,
            task_id,
            flow_id,
            assignment_id,
            attempt_id,
            source_dispatch_id,
        ],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["AttemptWaitModel"]

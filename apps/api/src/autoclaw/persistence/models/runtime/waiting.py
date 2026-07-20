from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import utcnow

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.command_runs import CommandRunModel
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowModel
    from autoclaw.persistence.models.runtime.human_requests import HumanRequestModel


class FlowWaitModel(RuntimeBase):
    __tablename__ = "flow_waits"
    __table_args__ = (
        CheckConstraint(
            "(human_request_id IS NOT NULL AND command_run_id IS NULL) OR "
            "(human_request_id IS NULL AND command_run_id IS NOT NULL)",
            name="ck_flow_waits_exactly_one_source",
        ),
        ForeignKeyConstraint(
            ["flow_id", "task_id", "required_current_dispatch_presence_marker"],
            ["flows.flow_id", "flows.task_id", "flows.current_dispatch_presence_marker"],
            name="fk_flow_waits_unoccupied_flow",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["human_request_id", "task_id", "flow_id", "source_dispatch_id"],
            [
                "human_requests.request_id",
                "human_requests.task_id",
                "human_requests.flow_id",
                "human_requests.source_dispatch_id",
            ],
            name="fk_flow_waits_human_request_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["command_run_id", "task_id", "flow_id", "source_dispatch_id"],
            [
                "command_runs.run_id",
                "command_runs.task_id",
                "command_runs.flow_id",
                "command_runs.source_dispatch_id",
            ],
            name="fk_flow_waits_command_run_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    flow_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    required_current_dispatch_presence_marker: Mapped[int] = mapped_column(
        Integer,
        Computed("0", persisted=True),
        nullable=False,
    )
    source_dispatch_id: Mapped[str] = mapped_column(
        ForeignKey("dispatch_turns.dispatch_id"),
        unique=True,
    )
    human_request_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    command_run_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        back_populates="wait",
        foreign_keys=[flow_id, task_id, required_current_dispatch_presence_marker],
        lazy="raise",
        viewonly=True,
    )
    source_dispatch: Mapped[DispatchTurnModel] = relationship(
        "DispatchTurnModel",
        back_populates="flow_wait",
        foreign_keys=[source_dispatch_id],
        lazy="raise",
    )
    human_request: Mapped[HumanRequestModel | None] = relationship(
        "HumanRequestModel",
        back_populates="flow_wait",
        foreign_keys=[human_request_id],
        lazy="raise",
        viewonly=True,
    )
    command_run: Mapped[CommandRunModel | None] = relationship(
        "CommandRunModel",
        back_populates="flow_wait",
        foreign_keys=[command_run_id],
        lazy="raise",
        viewonly=True,
    )


__all__ = ["FlowWaitModel"]

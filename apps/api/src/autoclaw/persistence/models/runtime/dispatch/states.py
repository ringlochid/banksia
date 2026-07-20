from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoclaw.persistence.base import RuntimeBase
from autoclaw.persistence.models.runtime.common import utcnow

if TYPE_CHECKING:
    from autoclaw.persistence.models.runtime.dispatch.turns import DispatchTurnModel
    from autoclaw.persistence.models.runtime.flow.runtime import FlowModel
    from autoclaw.persistence.models.runtime.task import TaskModel


class FlowStartSourceModel(RuntimeBase):
    __tablename__ = "flow_start_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_id", "task_id"],
            ["flows.flow_id", "flows.task_id"],
            name="fk_flow_start_sources_flow_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["flow_id", "successor_dispatch_id"],
            ["dispatch_turns.flow_start_source_flow_id", "dispatch_turns.dispatch_id"],
            name="fk_flow_start_sources_successor_owner",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    flow_id: Mapped[str] = mapped_column(ForeignKey("flows.flow_id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), unique=True, index=True)
    successor_dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    flow: Mapped[FlowModel] = relationship(
        "FlowModel",
        back_populates="start_source",
        foreign_keys=[flow_id],
        lazy="raise",
    )
    task: Mapped[TaskModel] = relationship(
        "TaskModel",
        foreign_keys=[task_id],
        lazy="raise",
    )
    successor_dispatch: Mapped[DispatchTurnModel | None] = relationship(
        "DispatchTurnModel",
        foreign_keys=[flow_id, successor_dispatch_id],
        lazy="raise",
        uselist=False,
        viewonly=True,
    )


__all__ = ["FlowStartSourceModel"]

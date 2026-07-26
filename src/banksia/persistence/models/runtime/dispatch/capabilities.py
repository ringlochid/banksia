from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banksia.persistence.base import RuntimeBase
from banksia.persistence.datetimes import UtcDateTime
from banksia.persistence.models.runtime.common import (
    CAPABILITY_DECISION_VALUES,
    CAPABILITY_SOURCE_VALUES,
    MANAGED_SANDBOX_MODE_VALUES,
    NETWORK_ACCESS_VALUES,
    PROVIDER_NATIVE_ACCESS_VALUES,
    PROVIDER_VALUES,
    sql_in,
    utcnow,
)

if TYPE_CHECKING:
    from banksia.persistence.models.runtime.dispatch.turns import DispatchTurnModel


class DispatchCapabilitySetModel(RuntimeBase):
    __tablename__ = "dispatch_capability_sets"
    __table_args__ = (
        CheckConstraint(
            f"provider_kind IN ({sql_in(PROVIDER_VALUES)})",
            name="ck_dispatch_capability_sets_provider_kind",
        ),
        CheckConstraint(
            f"provider_native_access IN ({sql_in(PROVIDER_NATIVE_ACCESS_VALUES)})",
            name="ck_dispatch_capability_sets_provider_native_access",
        ),
        CheckConstraint(
            f"provider_native_access_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
            name="ck_dispatch_capability_sets_provider_native_source",
        ),
        CheckConstraint(
            f"network_access IN ({sql_in(NETWORK_ACCESS_VALUES)})",
            name="ck_dispatch_capability_sets_network_access",
        ),
        CheckConstraint(
            f"network_access_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
            name="ck_dispatch_capability_sets_network_source",
        ),
        CheckConstraint(
            "(provider_kind = 'openclaw' AND requested_sandbox_mode IS NULL AND "
            "requested_sandbox_network IS NULL AND "
            "sandbox_request_source IS NULL AND effective_sandbox_mode IS NULL AND "
            "effective_sandbox_network IS NULL AND sandbox_mode_source IS NULL AND "
            "sandbox_network_source IS NULL) OR "
            f"(provider_kind IN ('codex', 'claude') AND "
            f"requested_sandbox_mode IN ({sql_in(MANAGED_SANDBOX_MODE_VALUES)}) AND "
            f"requested_sandbox_network IN ({sql_in(NETWORK_ACCESS_VALUES)}) AND "
            "sandbox_request_source IN ('default', 'member_configuration') AND "
            f"effective_sandbox_mode IN ({sql_in(MANAGED_SANDBOX_MODE_VALUES)}) AND "
            f"effective_sandbox_network IN ({sql_in(NETWORK_ACCESS_VALUES)}) AND "
            f"sandbox_mode_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)}) AND "
            f"sandbox_network_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)}))",
            name="ck_dispatch_capability_sets_sandbox_resolution",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((requested_sandbox_mode = 'read_only' AND requested_sandbox_network = 'deny') OR "
            "(requested_sandbox_mode = 'workspace_write') OR "
            "(requested_sandbox_mode = 'full_access' AND requested_sandbox_network = 'allow'))",
            name="ck_dispatch_capability_sets_requested_sandbox_pair",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR sandbox_request_source = 'member_configuration' OR "
            "(requested_sandbox_mode = 'full_access' AND "
            "requested_sandbox_network = 'allow')",
            name="ck_dispatch_capability_sets_default_sandbox_request",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((effective_sandbox_mode = 'read_only' AND effective_sandbox_network = 'deny') OR "
            "(effective_sandbox_mode = 'workspace_write') OR "
            "(effective_sandbox_mode = 'full_access' AND effective_sandbox_network = 'allow'))",
            name="ck_dispatch_capability_sets_effective_sandbox_pair",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((requested_sandbox_mode = 'read_only' AND effective_sandbox_mode = 'read_only') OR "
            "(requested_sandbox_mode = 'workspace_write' AND "
            "effective_sandbox_mode IN ('read_only', 'workspace_write')) OR "
            "(requested_sandbox_mode = 'full_access'))",
            name="ck_dispatch_capability_sets_sandbox_not_widened",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR requested_sandbox_network = 'allow' OR "
            "effective_sandbox_network = 'deny'",
            name="ck_dispatch_capability_sets_network_not_widened",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((effective_sandbox_mode = requested_sandbox_mode AND "
            "sandbox_mode_source = sandbox_request_source) OR "
            "(effective_sandbox_mode != requested_sandbox_mode AND "
            "sandbox_mode_source = 'controller'))",
            name="ck_dispatch_capability_sets_sandbox_mode_source_exact",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((effective_sandbox_network = requested_sandbox_network AND "
            "sandbox_network_source = sandbox_request_source) OR "
            "(effective_sandbox_network != requested_sandbox_network AND "
            "sandbox_network_source = 'controller'))",
            name="ck_dispatch_capability_sets_sandbox_network_source_exact",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "((effective_sandbox_mode = 'read_only' AND provider_native_access = 'denied') OR "
            "(effective_sandbox_mode = 'workspace_write' AND "
            "provider_native_access = 'restricted') OR "
            "(effective_sandbox_mode = 'full_access' AND provider_native_access = 'full'))",
            name="ck_dispatch_capability_sets_native_projection_exact",
        ),
        CheckConstraint(
            "provider_kind = 'openclaw' OR "
            "(provider_native_access_source = sandbox_mode_source AND "
            "network_access = effective_sandbox_network AND "
            "network_access_source = sandbox_network_source)",
            name="ck_dispatch_capability_sets_managed_projection_sources",
        ),
        CheckConstraint(
            "requested_human_request_source IN ('default', 'member_configuration')",
            name="ck_dispatch_capability_sets_requested_human_source",
        ),
        CheckConstraint(
            "requested_human_request_source = 'member_configuration' OR "
            "(requested_human_direction = 'deny' AND requested_human_approval = 'deny' AND "
            "requested_human_input = 'deny' AND requested_human_review = 'deny')",
            name="ck_dispatch_capability_sets_default_human_request",
        ),
        *(
            CheckConstraint(
                f"{column} IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
                name=f"ck_dispatch_capability_sets_{column}",
            )
            for column in (
                "human_direction_source",
                "human_approval_source",
                "human_input_source",
                "human_review_source",
            )
        ),
        CheckConstraint(
            "requested_command_run_source IN ('default', 'member_configuration')",
            name="ck_dispatch_capability_sets_requested_command_run_source",
        ),
        CheckConstraint(
            "requested_command_run_source = 'member_configuration' OR "
            "requested_command_run = 'deny'",
            name="ck_dispatch_capability_sets_default_command_run",
        ),
        CheckConstraint(
            f"command_run_source IN ({sql_in(CAPABILITY_SOURCE_VALUES)})",
            name="ck_dispatch_capability_sets_command_run_source",
        ),
        *(
            CheckConstraint(
                f"{column} IN ({sql_in(CAPABILITY_DECISION_VALUES)})",
                name=f"ck_dispatch_capability_sets_{column}",
            )
            for column in (
                "human_direction",
                "human_approval",
                "human_input",
                "human_review",
                "requested_human_direction",
                "requested_human_approval",
                "requested_human_input",
                "requested_human_review",
                "requested_command_run",
                "command_run",
            )
        ),
        *(
            CheckConstraint(
                f"({effective} = {requested} AND "
                f"{source} = requested_human_request_source) OR "
                f"({effective} = 'deny' AND {requested} = 'allow' AND "
                f"{source} = 'controller')",
                name=f"ck_dispatch_capability_sets_{effective}_not_widened",
            )
            for requested, effective, source in (
                ("requested_human_direction", "human_direction", "human_direction_source"),
                ("requested_human_approval", "human_approval", "human_approval_source"),
                ("requested_human_input", "human_input", "human_input_source"),
                ("requested_human_review", "human_review", "human_review_source"),
            )
        ),
        CheckConstraint(
            "(command_run = requested_command_run AND "
            "command_run_source = requested_command_run_source) OR "
            "(command_run = 'deny' AND requested_command_run = 'allow' AND "
            "command_run_source = 'controller')",
            name="ck_dispatch_capability_sets_command_run_not_widened",
        ),
        ForeignKeyConstraint(
            ["dispatch_id", "provider_kind"],
            ["dispatch_turns.dispatch_id", "dispatch_turns.resolved_provider"],
            name="fk_dispatch_capability_sets_provider_route",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    dispatch_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider_kind: Mapped[str] = mapped_column(String(64))
    provider_native_access: Mapped[str] = mapped_column(String(64))
    provider_native_access_source: Mapped[str] = mapped_column(String(64))
    network_access: Mapped[str] = mapped_column(String(64))
    network_access_source: Mapped[str] = mapped_column(String(64))
    requested_sandbox_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_sandbox_network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sandbox_request_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_sandbox_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_sandbox_network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sandbox_mode_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sandbox_network_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_human_direction: Mapped[str] = mapped_column(String(64))
    requested_human_approval: Mapped[str] = mapped_column(String(64))
    requested_human_input: Mapped[str] = mapped_column(String(64))
    requested_human_review: Mapped[str] = mapped_column(String(64))
    requested_human_request_source: Mapped[str] = mapped_column(String(64))
    human_direction: Mapped[str] = mapped_column(String(64))
    human_direction_source: Mapped[str] = mapped_column(String(64))
    human_approval: Mapped[str] = mapped_column(String(64))
    human_approval_source: Mapped[str] = mapped_column(String(64))
    human_input: Mapped[str] = mapped_column(String(64))
    human_input_source: Mapped[str] = mapped_column(String(64))
    human_review: Mapped[str] = mapped_column(String(64))
    human_review_source: Mapped[str] = mapped_column(String(64))
    requested_command_run: Mapped[str] = mapped_column(String(64))
    requested_command_run_source: Mapped[str] = mapped_column(String(64))
    command_run: Mapped[str] = mapped_column(String(64))
    command_run_source: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    dispatch: Mapped[DispatchTurnModel] = relationship(
        back_populates="capability_set",
        foreign_keys=[dispatch_id, provider_kind],
        lazy="raise",
    )


__all__ = ["DispatchCapabilitySetModel"]

from __future__ import annotations

from datetime import datetime

from banksia.persistence.models import DispatchCapabilitySetModel


def allowing_dispatch_capability_set(
    *,
    dispatch_id: str,
    created_at: datetime,
) -> DispatchCapabilitySetModel:
    """Build the explicit allowing capability snapshot used by runtime fixtures."""

    return DispatchCapabilitySetModel(
        dispatch_id=dispatch_id,
        provider_kind="codex",
        provider_native_access="full",
        provider_native_access_source="default",
        network_access="allow",
        network_access_source="default",
        requested_sandbox_mode="full_access",
        requested_sandbox_network="allow",
        sandbox_request_source="default",
        effective_sandbox_mode="full_access",
        effective_sandbox_network="allow",
        sandbox_mode_source="default",
        sandbox_network_source="default",
        requested_human_direction="allow",
        requested_human_approval="allow",
        requested_human_input="allow",
        requested_human_review="allow",
        requested_human_request_source="member_configuration",
        human_direction="allow",
        human_direction_source="member_configuration",
        human_approval="allow",
        human_approval_source="member_configuration",
        human_input="allow",
        human_input_source="member_configuration",
        human_review="allow",
        human_review_source="member_configuration",
        requested_command_run="allow",
        requested_command_run_source="member_configuration",
        command_run="allow",
        command_run_source="member_configuration",
        created_at=created_at,
    )


__all__ = ["allowing_dispatch_capability_set"]

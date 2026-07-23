from __future__ import annotations

from banksia.providers import NetworkAccess, ProviderNativeAccess
from banksia.runtime.capabilities import (
    capability_rejection_for_command_run,
    capability_rejection_for_human_request,
    default_effective_capabilities,
    resolve_effective_capabilities_from_member_request,
)
from banksia.runtime.contracts import (
    CapabilityCeilingSet,
    CapabilityDecision,
    CapabilitySource,
    HumanRequestKind,
    OperationFailureCode,
)
from banksia.workflows import MemberCapabilities


def test_omitted_member_capabilities_default_deny_controller_managed_operations() -> None:
    capabilities = resolve_effective_capabilities_from_member_request(None)

    assert capabilities.provider_native_access.effective is ProviderNativeAccess.FULL
    assert capabilities.provider_native_access.source is CapabilitySource.DEFAULT
    assert capabilities.network_access.effective is NetworkAccess.ALLOW
    assert capabilities.network_access.source is CapabilitySource.DEFAULT
    assert capabilities.requested_human_request.direction is CapabilityDecision.DENY
    assert capabilities.requested_human_request.approval is CapabilityDecision.DENY
    assert capabilities.requested_human_request.input is CapabilityDecision.DENY
    assert capabilities.requested_human_request.review is CapabilityDecision.DENY
    assert capabilities.human_request == capabilities.requested_human_request
    assert capabilities.requested_human_request_source is CapabilitySource.DEFAULT
    assert set(capabilities.human_request_sources.model_dump().values()) == {
        CapabilitySource.DEFAULT
    }
    assert capabilities.requested_command_run is CapabilityDecision.DENY
    assert capabilities.requested_command_run_source is CapabilitySource.DEFAULT
    assert capabilities.command_run is CapabilityDecision.DENY
    assert capabilities.command_run_source is CapabilitySource.DEFAULT


def test_member_configuration_grants_only_exact_authored_operations() -> None:
    capabilities = resolve_effective_capabilities_from_member_request(
        MemberCapabilities(
            human_request=("approval", "input"),
            command_run="allow",
        )
    )

    assert capabilities.requested_human_request.approval is CapabilityDecision.ALLOW
    assert capabilities.requested_human_request.input is CapabilityDecision.ALLOW
    assert capabilities.requested_human_request.direction is CapabilityDecision.DENY
    assert capabilities.requested_human_request.review is CapabilityDecision.DENY
    assert capabilities.human_request == capabilities.requested_human_request
    assert capabilities.requested_human_request_source is CapabilitySource.MEMBER_CONFIGURATION
    assert set(capabilities.human_request_sources.model_dump().values()) == {
        CapabilitySource.MEMBER_CONFIGURATION
    }
    assert capabilities.requested_command_run is CapabilityDecision.ALLOW
    assert capabilities.requested_command_run_source is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.command_run is CapabilityDecision.ALLOW
    assert capabilities.command_run_source is CapabilitySource.MEMBER_CONFIGURATION


def test_controller_can_narrow_but_never_widen_member_configuration() -> None:
    capabilities = resolve_effective_capabilities_from_member_request(
        {
            "human_request": ["approval", "input"],
            "command_run": "allow",
        },
        controller=CapabilityCeilingSet(
            provider_native_access=ProviderNativeAccess.RESTRICTED,
            network_access=NetworkAccess.DENY,
            allowed_human_request_kinds=(HumanRequestKind.INPUT,),
            command_run=CapabilityDecision.DENY,
        ),
    )

    assert capabilities.provider_native_access.effective is ProviderNativeAccess.RESTRICTED
    assert capabilities.provider_native_access.source is CapabilitySource.CONTROLLER
    assert capabilities.network_access.effective is NetworkAccess.DENY
    assert capabilities.network_access.source is CapabilitySource.CONTROLLER
    assert capabilities.requested_human_request.approval is CapabilityDecision.ALLOW
    assert capabilities.requested_human_request.input is CapabilityDecision.ALLOW
    assert capabilities.human_request.approval is CapabilityDecision.DENY
    assert capabilities.human_request.input is CapabilityDecision.ALLOW
    assert capabilities.requested_human_request_source is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.human_request_sources.approval is CapabilitySource.CONTROLLER
    assert capabilities.human_request_sources.input is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.human_request_sources.direction is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.human_request_sources.review is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.requested_command_run is CapabilityDecision.ALLOW
    assert capabilities.requested_command_run_source is CapabilitySource.MEMBER_CONFIGURATION
    assert capabilities.command_run is CapabilityDecision.DENY
    assert capabilities.command_run_source is CapabilitySource.CONTROLLER


def test_member_capabilities_do_not_inherit_from_another_member() -> None:
    parent = resolve_effective_capabilities_from_member_request(
        {"human_request": ["review"], "command_run": "allow"}
    )
    child = resolve_effective_capabilities_from_member_request(None)

    assert parent.human_request.review is CapabilityDecision.ALLOW
    assert parent.command_run is CapabilityDecision.ALLOW
    assert child.human_request.review is CapabilityDecision.DENY
    assert child.command_run is CapabilityDecision.DENY


def test_capability_rejection_names_target_and_next_action() -> None:
    capabilities = default_effective_capabilities()
    human_request_rejection = capability_rejection_for_human_request(capabilities, "review")
    command_run_rejection = capability_rejection_for_command_run(capabilities)

    assert human_request_rejection is not None
    assert human_request_rejection.code is OperationFailureCode.CAPABILITY_REJECTED
    assert human_request_rejection.capability == "human_request.review"
    assert "does not allow human_request.review" in human_request_rejection.message
    assert human_request_rejection.next_legal_action is None
    assert command_run_rejection is not None
    assert command_run_rejection.code is OperationFailureCode.CAPABILITY_REJECTED
    assert command_run_rejection.capability == "command_run"
    assert "controller-managed command_run" in command_run_rejection.message
    assert command_run_rejection.next_legal_action == (
        "avoid long command; for example, run focused tests one by one rather than the whole "
        "test suite"
    )


def test_capability_rejection_accepts_typed_human_request_kind() -> None:
    capabilities = resolve_effective_capabilities_from_member_request(
        {"human_request": ["direction"]}
    )

    assert (
        capability_rejection_for_human_request(
            capabilities,
            HumanRequestKind.DIRECTION,
        )
        is None
    )

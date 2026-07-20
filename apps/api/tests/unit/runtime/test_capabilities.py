from __future__ import annotations

from autoclaw.definitions.contracts import (
    NetworkAccess,
    PolicyDefinitionInput,
    ProviderNativeAccess,
)
from autoclaw.runtime.capabilities import (
    capability_rejection_for_command_run,
    capability_rejection_for_human_request,
    default_effective_capabilities,
    resolve_effective_capabilities_from_policy_content,
)
from autoclaw.runtime.contracts import (
    CapabilityCeilingSet,
    CapabilityDecision,
    CapabilitySource,
    OperationFailureCode,
)


def test_missing_policy_uses_axis_defaults_and_denies_special_capabilities() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(None)

    assert capabilities.provider_native_access.effective == ProviderNativeAccess.FULL
    assert capabilities.provider_native_access.source == CapabilitySource.DEFAULT
    assert capabilities.network_access.effective == NetworkAccess.ALLOW
    assert capabilities.network_access.source == CapabilitySource.DEFAULT
    assert capabilities.human_request.direction == CapabilityDecision.DENY
    assert capabilities.human_request.approval == CapabilityDecision.DENY
    assert capabilities.human_request.input == CapabilityDecision.DENY
    assert capabilities.human_request.review == CapabilityDecision.DENY
    assert capabilities.command_run == CapabilityDecision.DENY


def test_omitted_authored_axes_retain_default_source() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(
        {
            "id": "interactive-worker",
            "description": "Policy that omits provider-native and network ceilings.",
            "applies_to": ["worker"],
            "capabilities": {
                "human_request": {
                    "mode": "allow",
                    "allowed_kinds": ["direction"],
                }
            },
        }
    )

    assert capabilities.provider_native_access.source == CapabilitySource.DEFAULT
    assert capabilities.network_access.source == CapabilitySource.DEFAULT
    assert capabilities.human_request.direction == CapabilityDecision.ALLOW


def test_persisted_omission_retains_default_source() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "portable-worker",
            "description": "Policy that omits provider-native and network ceilings.",
            "applies_to": ["worker"],
        }
    )

    capabilities = resolve_effective_capabilities_from_policy_content(
        policy.model_dump(mode="json")
    )

    assert capabilities.provider_native_access.source == CapabilitySource.DEFAULT
    assert capabilities.network_access.source == CapabilitySource.DEFAULT


def test_explicit_authored_axes_are_attributed_to_policy_definition() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(
        {
            "id": "restricted-worker",
            "description": "Policy with explicit provider-native and network ceilings.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "restricted",
                "network_access": "deny",
            },
        }
    )

    assert capabilities.provider_native_access.effective == ProviderNativeAccess.RESTRICTED
    assert capabilities.provider_native_access.source == CapabilitySource.POLICY_DEFINITION
    assert capabilities.network_access.effective == NetworkAccess.DENY
    assert capabilities.network_access.source == CapabilitySource.POLICY_DEFINITION


def test_persisted_explicit_defaults_retain_policy_definition_source() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "explicit-defaults",
            "description": "Policy that explicitly authors the portable default ceilings.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "full",
                "network_access": "allow",
            },
        }
    )

    capabilities = resolve_effective_capabilities_from_policy_content(
        policy.model_dump(mode="json")
    )

    assert capabilities.provider_native_access.effective == ProviderNativeAccess.FULL
    assert capabilities.provider_native_access.source == CapabilitySource.POLICY_DEFINITION
    assert capabilities.network_access.effective == NetworkAccess.ALLOW
    assert capabilities.network_access.source == CapabilitySource.POLICY_DEFINITION


def test_capability_resolution_only_narrows_each_axis() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(
        {
            "id": "portable-worker",
            "description": "Policy that permits the portable default posture.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "full",
                "network_access": "allow",
            },
        },
        task_policy=CapabilityCeilingSet(provider_native_access=ProviderNativeAccess.RESTRICTED),
        controller=CapabilityCeilingSet(
            provider_native_access=ProviderNativeAccess.FULL,
            network_access=NetworkAccess.DENY,
        ),
    )

    assert capabilities.provider_native_access.effective == ProviderNativeAccess.RESTRICTED
    assert capabilities.provider_native_access.source == CapabilitySource.TASK_POLICY
    assert capabilities.network_access.effective == NetworkAccess.DENY
    assert capabilities.network_access.source == CapabilitySource.CONTROLLER


def test_equally_restrictive_capability_ties_use_highest_priority_source() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(
        {
            "id": "denied-worker",
            "description": "Policy with maximum portable restrictions.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "denied",
                "network_access": "deny",
            },
        },
        task_policy=CapabilityCeilingSet(
            provider_native_access=ProviderNativeAccess.DENIED,
            network_access=NetworkAccess.DENY,
        ),
        controller=CapabilityCeilingSet(
            provider_native_access=ProviderNativeAccess.DENIED,
            network_access=NetworkAccess.DENY,
        ),
    )

    assert capabilities.provider_native_access.source == CapabilitySource.CONTROLLER
    assert capabilities.network_access.source == CapabilitySource.CONTROLLER


def test_effective_capabilities_ignore_stale_allowed_kinds_under_deny() -> None:
    capabilities = resolve_effective_capabilities_from_policy_content(
        {
            "id": "quiet-worker",
            "description": "Policy with stale request kinds under deny.",
            "applies_to": ["worker"],
            "capabilities": {
                "human_request": {
                    "mode": "deny",
                    "allowed_kinds": ["review"],
                },
                "command_run": "deny",
            },
        }
    )

    assert capabilities.human_request.review == CapabilityDecision.DENY
    assert capabilities.command_run == CapabilityDecision.DENY


def test_effective_capabilities_keep_human_and_command_axes_separate() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "interactive-command-worker",
            "description": "Policy that grants selected controller-managed capabilities.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "denied",
                "network_access": "deny",
                "human_request": {
                    "mode": "allow",
                    "allowed_kinds": ["approval", "input"],
                },
                "command_run": "allow",
            },
        }
    )

    capabilities = resolve_effective_capabilities_from_policy_content(policy)

    assert capabilities.provider_native_access.effective == ProviderNativeAccess.DENIED
    assert capabilities.network_access.effective == NetworkAccess.DENY
    assert capabilities.human_request.approval == CapabilityDecision.ALLOW
    assert capabilities.human_request.input == CapabilityDecision.ALLOW
    assert capabilities.human_request.direction == CapabilityDecision.DENY
    assert capabilities.human_request.review == CapabilityDecision.DENY
    assert capabilities.command_run == CapabilityDecision.ALLOW


def test_capability_rejection_names_target_and_next_action() -> None:
    capabilities = default_effective_capabilities()
    human_request_rejection = capability_rejection_for_human_request(capabilities, "review")
    command_run_rejection = capability_rejection_for_command_run(capabilities)

    assert human_request_rejection is not None
    assert human_request_rejection.code == OperationFailureCode.CAPABILITY_REJECTED
    assert human_request_rejection.capability == "human_request.review"
    assert "does not allow human_request.review" in human_request_rejection.message
    assert human_request_rejection.next_legal_action is None
    assert command_run_rejection is not None
    assert command_run_rejection.code == OperationFailureCode.CAPABILITY_REJECTED
    assert command_run_rejection.capability == "command_run"
    assert "controller-managed command_run" in command_run_rejection.message
    assert command_run_rejection.next_legal_action == (
        "avoid long command; for example, run focused tests one by one rather than the whole "
        "test suite"
    )

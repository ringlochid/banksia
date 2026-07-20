from __future__ import annotations

import warnings
from typing import Any

import pytest
from autoclaw.definitions.contracts import (
    CapabilityDecision as AuthoredCapabilityDecision,
)
from autoclaw.definitions.contracts import (
    HumanRequestKind as AuthoredHumanRequestKind,
)
from autoclaw.definitions.contracts import (
    PolicyDefinitionFile,
    PolicyDefinitionInput,
    ProviderKind,
    RoleDefinitionFile,
    RoleDefinitionInput,
)
from autoclaw.runtime.contracts import (
    CapabilityDecision as RuntimeCapabilityDecision,
)
from autoclaw.runtime.contracts import (
    HumanRequestKind as RuntimeHumanRequestKind,
)
from pydantic import ValidationError

from .support import RoleOrPolicyDefinitionModel


@pytest.mark.parametrize(
    ("model_type", "payload"),
    [
        (
            RoleDefinitionFile,
            {
                "id": "review-role",
                "title": "Review role",
                "description": "Role without file kind.",
                "allowed_node_kinds": ["parent"],
            },
        ),
        (
            PolicyDefinitionFile,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Policy without file kind.",
                "applies_to": ["parent"],
                "budget_spec": {"child_assignment_limit": 3},
            },
        ),
    ],
)
def test_role_and_policy_file_models_require_kind(
    model_type: type[RoleDefinitionFile] | type[PolicyDefinitionFile],
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="kind"):
        model_type.model_validate(payload)


@pytest.mark.parametrize(
    ("model_type", "payload", "error_match"),
    [
        (
            RoleDefinitionInput,
            {
                "id": "review-role",
                "title": "Review role",
                "description": "Legacy role default policy should be rejected.",
                "allowed_node_kinds": ["parent"],
                "default_policy": "review-policy",
            },
            "default_policy",
        ),
        (
            RoleDefinitionInput,
            {
                "id": "review-role",
                "title": "Review role",
                "description": "Legacy allowed_kinds should be rejected.",
                "allowed_kinds": ["parent"],
            },
            "allowed_kinds|allowed_node_kinds",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Legacy defaults should be rejected.",
                "applies_to": ["parent"],
                "defaults": {"retry_budget": 1},
            },
            "defaults",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Legacy rules should be rejected.",
                "applies_to": ["worker"],
                "rules": {"allowed_tools": ["shell"]},
            },
            "rules",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Legacy same-attempt grammar should be rejected.",
                "applies_to": ["worker"],
                "same_attempt_redispatch_limit": 1,
            },
            "same_attempt_redispatch_limit",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Legacy budget grammar should be rejected.",
                "applies_to": ["worker"],
                "budget_spec": {"same_attempt_continue_limit": 1},
            },
            "same_attempt_continue_limit",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Budget limits must reject string numerics.",
                "applies_to": ["worker"],
                "budget_spec": {"retry_limit": "2"},
            },
            "retry_limit",
        ),
        (
            RoleDefinitionInput,
            {
                "id": "review-role",
                "title": "Review role",
                "description": "Missing allowed_node_kinds should fail required-field validation.",
            },
            "allowed_node_kinds",
        ),
        (
            PolicyDefinitionInput,
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Missing applies_to should fail required-field validation.",
            },
            "applies_to",
        ),
    ],
)
def test_role_and_policy_definition_schema_reject_matrix_parity(
    model_type: RoleOrPolicyDefinitionModel,
    payload: dict[str, Any],
    error_match: str,
) -> None:
    with pytest.raises(ValidationError, match=error_match):
        model_type.model_validate(payload)


def test_role_definition_schema_accepts_display_metadata() -> None:
    role = RoleDefinitionInput.model_validate(
        {
            "id": "review-role",
            "title": "Review role",
            "description": "Role with portable display metadata.",
            "allowed_node_kinds": ["worker"],
            "labels": ["review", "human"],
        }
    )

    assert role.title == "Review role"
    assert role.labels == ["review", "human"]


def test_role_definition_schema_accepts_missing_title_for_existing_definitions() -> None:
    role = RoleDefinitionInput.model_validate(
        {
            "id": "review-role",
            "description": "Existing role without display metadata.",
            "allowed_node_kinds": ["worker"],
        }
    )

    assert role.title is None


def test_policy_definition_schema_accepts_missing_title_for_existing_definitions() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "review-policy",
            "description": "Existing policy without display metadata.",
            "applies_to": ["worker"],
        }
    )

    assert policy.title is None
    assert policy.capabilities.provider_native_access == "full"
    assert policy.capabilities.network_access == "allow"
    assert policy.capabilities.human_request.mode == "deny"
    assert policy.capabilities.command_run == "deny"


def test_policy_definition_schema_defaults_to_denied_capabilities() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "review-policy",
            "title": "Review policy",
            "description": "Policy with default capability posture.",
            "applies_to": ["worker"],
        }
    )

    assert policy.capabilities.provider_native_access == "full"
    assert policy.capabilities.network_access == "allow"
    assert policy.capabilities.human_request.mode == "deny"
    assert policy.capabilities.human_request.allowed_kinds == []
    assert policy.capabilities.command_run == "deny"
    assert policy.labels == []


def test_policy_serialization_preserves_omitted_axis_provenance() -> None:
    omitted = PolicyDefinitionInput.model_validate(
        {
            "id": "omitted-axis-policy",
            "description": "Policy that inherits native and network defaults.",
            "applies_to": ["worker"],
        }
    )
    explicit = PolicyDefinitionInput.model_validate(
        {
            "id": "explicit-axis-policy",
            "description": "Policy that explicitly authors the permissive values.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "full",
                "network_access": "allow",
            },
        }
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        omitted_dump = omitted.model_dump(mode="json")
        explicit_dump = explicit.model_dump(mode="json")

    omitted_capabilities = omitted_dump["capabilities"]
    explicit_capabilities = explicit_dump["capabilities"]

    assert "provider_native_access" not in omitted_capabilities
    assert "network_access" not in omitted_capabilities
    assert explicit_capabilities["provider_native_access"] == "full"
    assert explicit_capabilities["network_access"] == "allow"

    persisted_omitted = PolicyDefinitionInput.model_validate(omitted_dump)
    persisted_explicit = PolicyDefinitionInput.model_validate(explicit_dump)

    assert "provider_native_access" not in persisted_omitted.capabilities.model_fields_set
    assert "network_access" not in persisted_omitted.capabilities.model_fields_set
    assert "provider_native_access" in persisted_explicit.capabilities.model_fields_set
    assert "network_access" in persisted_explicit.capabilities.model_fields_set


def test_policy_definition_schema_accepts_portable_capability_grants() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "review-policy",
            "title": "Review policy",
            "description": "Policy with explicit portable capabilities.",
            "applies_to": ["worker"],
            "capabilities": {
                "provider_native_access": "restricted",
                "network_access": "deny",
                "human_request": {
                    "mode": "allow",
                    "allowed_kinds": ["direction", "review"],
                },
                "command_run": "allow",
            },
            "labels": ["interactive"],
        }
    )

    assert policy.capabilities.provider_native_access == "restricted"
    assert policy.capabilities.network_access == "deny"
    assert policy.capabilities.human_request.mode == "allow"
    assert policy.capabilities.human_request.allowed_kinds == ["direction", "review"]
    assert policy.capabilities.command_run == "allow"
    assert policy.labels == ["interactive"]


def test_policy_definition_schema_denied_human_requests_ignore_stale_allowed_kinds() -> None:
    policy = PolicyDefinitionInput.model_validate(
        {
            "id": "review-policy",
            "title": "Review policy",
            "description": "Policy with denied human request capability.",
            "applies_to": ["worker"],
            "capabilities": {
                "human_request": {
                    "mode": "deny",
                    "allowed_kinds": ["review"],
                },
            },
        }
    )

    assert policy.capabilities.human_request.mode == "deny"
    assert policy.capabilities.human_request.allowed_kinds == ["review"]


@pytest.mark.parametrize(
    ("capabilities", "error_match"),
    [
        (
            {"human_request": {"mode": "allow", "allowed_kinds": []}},
            "allowed_kinds",
        ),
        (
            {"human_request": {"mode": "maybe", "allowed_kinds": ["review"]}},
            "mode",
        ),
        (
            {"human_request": {"mode": "allow", "allowed_kinds": ["handoff"]}},
            "allowed_kinds",
        ),
        (
            {"command_run": "prompt"},
            "command_run",
        ),
        (
            {"provider_native_access": "root"},
            "provider_native_access",
        ),
        (
            {"network_access": "prompt"},
            "network_access",
        ),
    ],
)
def test_policy_definition_schema_rejects_unknown_capability_grammar(
    capabilities: dict[str, Any],
    error_match: str,
) -> None:
    with pytest.raises(ValidationError, match=error_match):
        PolicyDefinitionInput.model_validate(
            {
                "id": "review-policy",
                "title": "Review policy",
                "description": "Policy with illegal capability grammar.",
                "applies_to": ["worker"],
                "capabilities": capabilities,
            }
        )


def test_definition_policy_and_runtime_capability_vocabularies_stay_aligned() -> None:
    assert {decision.value for decision in AuthoredCapabilityDecision} == {
        decision.value for decision in RuntimeCapabilityDecision
    }
    assert {kind.value for kind in AuthoredHumanRequestKind} == {
        kind.value for kind in RuntimeHumanRequestKind
    }


def test_workflow_provider_kinds_are_exact() -> None:
    assert {provider.value for provider in ProviderKind} == {
        "claude",
        "codex",
        "openclaw",
    }

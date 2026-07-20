from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.registry import (
    CapabilityDecision as AuthoredCapabilityDecision,
)
from autoclaw.definitions.contracts.registry import (
    NetworkAccess,
    PolicyDefinitionInput,
    ProviderNativeAccess,
)
from autoclaw.persistence.models import FlowNodeModel, PolicyRevisionModel
from autoclaw.runtime.contracts.capabilities import (
    CapabilityCeilingSet,
    CapabilityRejectionError,
    CapabilitySource,
    EffectiveCapabilitySet,
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
    HumanRequestCapabilitySet,
)
from autoclaw.runtime.contracts.primitives import CapabilityDecision, HumanRequestKind

HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION = None
COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION = (
    "avoid long command; for example, run focused tests one by one rather than the whole test suite"
)

_SOURCE_PRIORITY = {
    CapabilitySource.DEFAULT: 0,
    CapabilitySource.POLICY_DEFINITION: 1,
    CapabilitySource.TASK_POLICY: 2,
    CapabilitySource.CONTROLLER: 3,
}
_PROVIDER_NATIVE_RESTRICTION = {
    ProviderNativeAccess.FULL: 0,
    ProviderNativeAccess.RESTRICTED: 1,
    ProviderNativeAccess.DENIED: 2,
}
_NETWORK_RESTRICTION = {
    NetworkAccess.ALLOW: 0,
    NetworkAccess.DENY: 1,
}


async def resolve_effective_capabilities_for_node(
    session: AsyncSession,
    *,
    node: FlowNodeModel,
    task_policy: CapabilityCeilingSet | None = None,
    controller: CapabilityCeilingSet | None = None,
) -> EffectiveCapabilitySet:
    policy_content = await _pinned_policy_content(session, node=node)
    return resolve_effective_capabilities_from_policy_content(
        policy_content,
        task_policy=task_policy,
        controller=controller,
    )


def resolve_effective_capabilities_from_policy_content(
    policy_content: Mapping[str, object] | PolicyDefinitionInput | None,
    *,
    task_policy: CapabilityCeilingSet | None = None,
    controller: CapabilityCeilingSet | None = None,
) -> EffectiveCapabilitySet:
    policy = _policy_definition(policy_content)
    explicitly_authored_axes = _explicitly_authored_capability_axes(policy_content, policy)

    native_candidates = [(ProviderNativeAccess.FULL, CapabilitySource.DEFAULT)]
    network_candidates = [(NetworkAccess.ALLOW, CapabilitySource.DEFAULT)]
    if policy is not None:
        if "provider_native_access" in explicitly_authored_axes:
            native_candidates.append(
                (
                    policy.capabilities.provider_native_access,
                    CapabilitySource.POLICY_DEFINITION,
                )
            )
        if "network_access" in explicitly_authored_axes:
            network_candidates.append(
                (policy.capabilities.network_access, CapabilitySource.POLICY_DEFINITION)
            )
    _append_ceiling_candidates(
        native_candidates=native_candidates,
        network_candidates=network_candidates,
        ceilings=task_policy,
        source=CapabilitySource.TASK_POLICY,
    )
    _append_ceiling_candidates(
        native_candidates=native_candidates,
        network_candidates=network_candidates,
        ceilings=controller,
        source=CapabilitySource.CONTROLLER,
    )

    native_effective, native_source = max(
        native_candidates,
        key=lambda item: (
            _PROVIDER_NATIVE_RESTRICTION[item[0]],
            _SOURCE_PRIORITY[item[1]],
        ),
    )
    network_effective, network_source = max(
        network_candidates,
        key=lambda item: (
            _NETWORK_RESTRICTION[item[0]],
            _SOURCE_PRIORITY[item[1]],
        ),
    )
    return EffectiveCapabilitySet(
        provider_native_access=EffectiveProviderNativeAccess(
            effective=native_effective,
            source=native_source,
        ),
        network_access=EffectiveNetworkAccess(
            effective=network_effective,
            source=network_source,
        ),
        human_request=_resolve_human_request_capabilities(policy),
        command_run=_resolve_command_run_capability(policy),
    )


def default_effective_capabilities() -> EffectiveCapabilitySet:
    return EffectiveCapabilitySet()


def capability_rejection_for_human_request(
    capabilities: EffectiveCapabilitySet,
    request_kind: HumanRequestKind | str,
) -> CapabilityRejectionError | None:
    normalized_kind = _human_request_kind(request_kind)
    decision = getattr(capabilities.human_request, normalized_kind.value)
    if decision == CapabilityDecision.ALLOW:
        return None
    capability = f"human_request.{normalized_kind.value}"
    return CapabilityRejectionError(
        capability=capability,
        message=f"current node policy does not allow {capability} from this node",
        next_legal_action=HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION,
    )


def capability_rejection_for_command_run(
    capabilities: EffectiveCapabilitySet,
) -> CapabilityRejectionError | None:
    if capabilities.command_run == CapabilityDecision.ALLOW:
        return None
    return CapabilityRejectionError(
        capability="command_run",
        message=(
            "current node policy does not allow controller-managed command_run from this node"
        ),
        next_legal_action=COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION,
    )


def _policy_definition(
    policy_content: Mapping[str, object] | PolicyDefinitionInput | None,
) -> PolicyDefinitionInput | None:
    if policy_content is None:
        return None
    if isinstance(policy_content, PolicyDefinitionInput):
        return policy_content
    return PolicyDefinitionInput.model_validate(policy_content)


def _explicitly_authored_capability_axes(
    policy_content: Mapping[str, object] | PolicyDefinitionInput | None,
    policy: PolicyDefinitionInput | None,
) -> frozenset[str]:
    if policy is None:
        return frozenset()
    if isinstance(policy_content, Mapping):
        capabilities = policy_content.get("capabilities")
        if isinstance(capabilities, Mapping):
            return frozenset(str(key) for key in capabilities)
        return frozenset()
    return frozenset(policy.capabilities.model_fields_set)


def _append_ceiling_candidates(
    *,
    native_candidates: list[tuple[ProviderNativeAccess, CapabilitySource]],
    network_candidates: list[tuple[NetworkAccess, CapabilitySource]],
    ceilings: CapabilityCeilingSet | None,
    source: CapabilitySource,
) -> None:
    if ceilings is None:
        return
    if ceilings.provider_native_access is not None:
        native_candidates.append((ceilings.provider_native_access, source))
    if ceilings.network_access is not None:
        network_candidates.append((ceilings.network_access, source))


def _resolve_human_request_capabilities(
    policy: PolicyDefinitionInput | None,
) -> HumanRequestCapabilitySet:
    if policy is None or policy.capabilities.human_request.mode != AuthoredCapabilityDecision.ALLOW:
        return HumanRequestCapabilitySet()

    allowed_kinds = {
        HumanRequestKind(kind.value) for kind in policy.capabilities.human_request.allowed_kinds
    }
    return HumanRequestCapabilitySet(
        direction=_human_request_decision(HumanRequestKind.DIRECTION, allowed_kinds),
        approval=_human_request_decision(HumanRequestKind.APPROVAL, allowed_kinds),
        input=_human_request_decision(HumanRequestKind.INPUT, allowed_kinds),
        review=_human_request_decision(HumanRequestKind.REVIEW, allowed_kinds),
    )


def _resolve_command_run_capability(
    policy: PolicyDefinitionInput | None,
) -> CapabilityDecision:
    if policy is not None and policy.capabilities.command_run == AuthoredCapabilityDecision.ALLOW:
        return CapabilityDecision.ALLOW
    return CapabilityDecision.DENY


def _human_request_decision(
    request_kind: HumanRequestKind,
    allowed_kinds: set[HumanRequestKind],
) -> CapabilityDecision:
    if request_kind in allowed_kinds:
        return CapabilityDecision.ALLOW
    return CapabilityDecision.DENY


def _human_request_kind(request_kind: HumanRequestKind | str) -> HumanRequestKind:
    if isinstance(request_kind, HumanRequestKind):
        return request_kind
    return HumanRequestKind(request_kind)


async def _pinned_policy_content(
    session: AsyncSession,
    *,
    node: FlowNodeModel,
) -> Mapping[str, object] | None:
    if node.policy_key is None or node.policy_revision_no is None:
        return None
    revision = await session.scalar(
        select(PolicyRevisionModel).where(
            PolicyRevisionModel.policy_key == node.policy_key,
            PolicyRevisionModel.revision_no == node.policy_revision_no,
        )
    )
    if revision is None:
        return None
    return revision.content_json


__all__ = [
    "COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION",
    "HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION",
    "capability_rejection_for_command_run",
    "capability_rejection_for_human_request",
    "default_effective_capabilities",
    "resolve_effective_capabilities_for_node",
    "resolve_effective_capabilities_from_policy_content",
]

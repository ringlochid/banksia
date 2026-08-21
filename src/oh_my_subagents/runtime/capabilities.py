from __future__ import annotations

from collections.abc import Collection, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import MemberConfigurationModel
from oh_my_subagents.providers import NetworkAccess, ProviderNativeAccess
from oh_my_subagents.runtime.contracts.capabilities import (
    CapabilityCeilingSet,
    CapabilityRejectionError,
    CapabilitySource,
    EffectiveCapabilitySet,
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
    HumanRequestCapabilitySet,
    HumanRequestCapabilitySources,
)
from oh_my_subagents.runtime.contracts.primitives import CapabilityDecision, HumanRequestKind
from oh_my_subagents.workflows.contracts import MemberCapabilities

HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION = None
COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION = (
    "avoid long command; for example, run focused tests one by one rather than the whole test suite"
)


async def resolve_effective_capabilities_for_member_configuration(
    session: AsyncSession,
    *,
    task_id: str,
    member_configuration_id: str,
    controller: CapabilityCeilingSet | None = None,
) -> EffectiveCapabilitySet:
    configuration = await session.scalar(
        select(MemberConfigurationModel).where(
            MemberConfigurationModel.task_id == task_id,
            MemberConfigurationModel.member_configuration_id == member_configuration_id,
        )
    )
    if configuration is None:
        raise ValueError(
            f"MemberConfiguration {member_configuration_id!r} does not belong to Task {task_id!r}"
        )
    return resolve_effective_capabilities_from_member_request(
        configuration.requested_capabilities_json,
        controller=controller,
    )


def resolve_effective_capabilities_from_member_request(
    requested: Mapping[str, object] | MemberCapabilities | None,
    *,
    controller: CapabilityCeilingSet | None = None,
) -> EffectiveCapabilitySet:
    """Resolve one Member's default-deny request with controller narrowing only."""

    authored = _member_capabilities(requested)
    (
        requested_human,
        requested_human_source,
        effective_human,
        human_sources,
    ) = _resolve_human_request_capabilities(authored, controller)
    (
        requested_command_run,
        requested_command_run_source,
        command_run,
        command_run_source,
    ) = _resolve_command_run_capability(authored, controller)
    provider_native_access, network_access = _resolve_provider_access_capabilities(controller)
    return EffectiveCapabilitySet(
        provider_native_access=provider_native_access,
        network_access=network_access,
        requested_human_request=requested_human,
        requested_human_request_source=requested_human_source,
        human_request=effective_human,
        human_request_sources=human_sources,
        requested_command_run=requested_command_run,
        requested_command_run_source=requested_command_run_source,
        command_run=command_run,
        command_run_source=command_run_source,
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
        message=f"current Member configuration does not allow {capability}",
        next_legal_action=HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION,
    )


def capability_rejection_for_command_run(
    capabilities: EffectiveCapabilitySet,
) -> CapabilityRejectionError | None:
    if capabilities.command_run == CapabilityDecision.ALLOW:
        return None
    return CapabilityRejectionError(
        capability="command_run",
        message=("current Member configuration does not allow controller-managed command_run"),
        next_legal_action=COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION,
    )


def _resolve_human_request_capabilities(
    authored: MemberCapabilities | None,
    controller: CapabilityCeilingSet | None,
) -> tuple[
    HumanRequestCapabilitySet,
    CapabilitySource,
    HumanRequestCapabilitySet,
    HumanRequestCapabilitySources,
]:
    requested_human = set(authored.human_request or ()) if authored is not None else set()
    effective_human = set(requested_human)
    requested_human_source = (
        CapabilitySource.MEMBER_CONFIGURATION
        if authored is not None and authored.human_request is not None
        else CapabilitySource.DEFAULT
    )
    human_sources = {kind.value: requested_human_source for kind in HumanRequestKind}
    if controller is not None and controller.allowed_human_request_kinds is not None:
        effective_human.intersection_update(controller.allowed_human_request_kinds)
        for removed_kind in requested_human - effective_human:
            human_sources[removed_kind] = CapabilitySource.CONTROLLER
    return (
        _human_request_capability_set(requested_human),
        requested_human_source,
        _human_request_capability_set(effective_human),
        HumanRequestCapabilitySources(
            direction=human_sources[HumanRequestKind.DIRECTION.value],
            approval=human_sources[HumanRequestKind.APPROVAL.value],
            input=human_sources[HumanRequestKind.INPUT.value],
            review=human_sources[HumanRequestKind.REVIEW.value],
        ),
    )


def _resolve_command_run_capability(
    authored: MemberCapabilities | None,
    controller: CapabilityCeilingSet | None,
) -> tuple[
    CapabilityDecision,
    CapabilitySource,
    CapabilityDecision,
    CapabilitySource,
]:
    requested_command_run = (
        CapabilityDecision.ALLOW
        if authored is not None and authored.command_run == "allow"
        else CapabilityDecision.DENY
    )
    command_run = requested_command_run
    command_run_source = (
        CapabilitySource.MEMBER_CONFIGURATION
        if authored is not None and authored.command_run is not None
        else CapabilitySource.DEFAULT
    )
    if controller is not None and controller.command_run is CapabilityDecision.DENY:
        command_run = CapabilityDecision.DENY
        if command_run != requested_command_run:
            command_run_source = CapabilitySource.CONTROLLER
    return (
        requested_command_run,
        (
            CapabilitySource.MEMBER_CONFIGURATION
            if authored is not None and authored.command_run is not None
            else CapabilitySource.DEFAULT
        ),
        command_run,
        command_run_source,
    )


def _resolve_provider_access_capabilities(
    controller: CapabilityCeilingSet | None,
) -> tuple[EffectiveProviderNativeAccess, EffectiveNetworkAccess]:
    return (
        EffectiveProviderNativeAccess(
            effective=(
                controller.provider_native_access
                if controller is not None and controller.provider_native_access is not None
                else ProviderNativeAccess.FULL
            ),
            source=(
                CapabilitySource.CONTROLLER
                if controller is not None and controller.provider_native_access is not None
                else CapabilitySource.DEFAULT
            ),
        ),
        EffectiveNetworkAccess(
            effective=(
                controller.network_access
                if controller is not None and controller.network_access is not None
                else NetworkAccess.ALLOW
            ),
            source=(
                CapabilitySource.CONTROLLER
                if controller is not None and controller.network_access is not None
                else CapabilitySource.DEFAULT
            ),
        ),
    )


def _human_request_capability_set(
    allowed: Collection[str],
) -> HumanRequestCapabilitySet:
    return HumanRequestCapabilitySet(
        direction=_decision("direction", allowed),
        approval=_decision("approval", allowed),
        input=_decision("input", allowed),
        review=_decision("review", allowed),
    )


def _member_capabilities(
    requested: Mapping[str, object] | MemberCapabilities | None,
) -> MemberCapabilities | None:
    if requested is None:
        return None
    if isinstance(requested, MemberCapabilities):
        return requested
    return MemberCapabilities.model_validate(requested)


def _decision(kind: str, allowed: Collection[str]) -> CapabilityDecision:
    return CapabilityDecision.ALLOW if kind in allowed else CapabilityDecision.DENY


def _human_request_kind(request_kind: HumanRequestKind | str) -> HumanRequestKind:
    if isinstance(request_kind, HumanRequestKind):
        return request_kind
    return HumanRequestKind(request_kind)


__all__ = [
    "COMMAND_RUN_DENIED_NEXT_LEGAL_ACTION",
    "HUMAN_REQUEST_DENIED_NEXT_LEGAL_ACTION",
    "capability_rejection_for_command_run",
    "capability_rejection_for_human_request",
    "default_effective_capabilities",
    "resolve_effective_capabilities_for_member_configuration",
    "resolve_effective_capabilities_from_member_request",
]

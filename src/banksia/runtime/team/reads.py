from __future__ import annotations

from typing import Literal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AssignmentModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    TeamRevisionMemberModel,
)
from banksia.runtime.capabilities import resolve_effective_capabilities_from_member_request
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.primitives import CapabilityDecision, HumanRequestKind
from banksia.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    OpenClawProviderRoute,
    ProviderResolution,
)
from banksia.runtime.contracts.team_read import (
    DirectTeamMemberRead,
    EffectiveCapabilitiesRead,
    MemberAvailability,
    MemberParticipation,
    ResolvedProviderRead,
    ResolvedSandboxRead,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.node_operations.catalog import (
    NodeOperationSelection,
    select_node_operation_descriptors,
)
from banksia.runtime.node_operations.contracts import NodeOperationName
from banksia.runtime.providers import (
    narrow_provider_capabilities,
    provider_selection_from_mapping,
    resolve_provider_route,
)
from banksia.runtime.team.participation import (
    ParticipationBasis,
    read_accepted_green_participation_bases,
)

type ConfigurationKey = tuple[str, str, str]
type MemberKey = tuple[str, str]
type ResolvedDirectMember = tuple[
    TeamRevisionMemberModel,
    MemberConfigurationModel,
    EffectiveCapabilitySet,
    ProviderResolution,
]


async def read_direct_team_members(
    session: AsyncSession,
    *,
    children: tuple[TeamRevisionMemberModel, ...],
    dependencies: DispatchOpeningDependencies,
) -> tuple[DirectTeamMemberRead, ...]:
    """Read one direct team from exact immutable Team selections."""

    if not children:
        return ()
    configurations = await _read_direct_team_configurations(session, children)
    resolved: list[ResolvedDirectMember] = []
    for child in children:
        configuration = configurations.get(
            (child.task_id, child.member_id, child.member_configuration_id)
        )
        if configuration is None:
            raise ValueError(f"Team Member {child.member_id!r} is missing its configuration")
        capabilities = resolve_effective_capabilities_from_member_request(
            configuration.requested_capabilities_json
        )
        provider = resolve_provider_route(
            provider=provider_selection_from_mapping(configuration.requested_provider_json),
            settings=dependencies.settings,
            available_adapter_kinds=dependencies.available_adapter_kinds,
        )
        capabilities = narrow_provider_capabilities(
            route=provider.route,
            sandbox=provider.sandbox,
            capabilities=capabilities,
        )
        resolved.append((child, configuration, capabilities, provider))
    busy_members = await _read_busy_direct_team_members(session, children)
    participating_bases = await read_accepted_green_participation_bases(
        session,
        bases=tuple(_participation_basis(child) for child in children),
    )
    return tuple(
        _direct_team_member_read(
            child,
            configuration=configuration,
            capabilities=capabilities,
            provider=provider,
            busy_members=busy_members,
            participating_bases=participating_bases,
        )
        for child, configuration, capabilities, provider in resolved
    )


def effective_capabilities_read(
    capabilities: EffectiveCapabilitySet | object,
) -> EffectiveCapabilitiesRead:
    allowed_human = tuple(
        kind
        for kind, field_name in (
            (HumanRequestKind.INPUT, "input"),
            (HumanRequestKind.DIRECTION, "direction"),
            (HumanRequestKind.APPROVAL, "approval"),
            (HumanRequestKind.REVIEW, "review"),
        )
        if _capability_value(
            getattr(
                getattr(capabilities, "human_request", None),
                field_name,
                getattr(capabilities, f"human_{field_name}", "deny"),
            )
        )
        == "allow"
    )
    return EffectiveCapabilitiesRead(
        human_request=allowed_human,
        command_run=_capability_value(getattr(capabilities, "command_run", "deny")),
    )


def resolved_provider_read(provider: ProviderResolution) -> ResolvedProviderRead:
    route = provider.route
    sandbox = (
        ResolvedSandboxRead(
            mode=provider.sandbox.effective_mode.value,
            network=provider.sandbox.effective_network.value,
        )
        if provider.sandbox is not None
        else None
    )
    if isinstance(route, CodexProviderRoute | ClaudeProviderRoute):
        return ResolvedProviderRead(
            kind=route.kind.value,
            model=route.model_override,
            effort=route.effort_override,
            sandbox=sandbox,
        )
    assert isinstance(route, OpenClawProviderRoute)
    return ResolvedProviderRead(kind=route.kind.value, gateway_profile=route.gateway_profile)


def persisted_provider_read(
    dispatch: DispatchTurnModel,
    capabilities: DispatchCapabilitySetModel,
) -> ResolvedProviderRead:
    sandbox = None
    if (
        capabilities.effective_sandbox_mode is not None
        and capabilities.effective_sandbox_network is not None
    ):
        sandbox = ResolvedSandboxRead(
            mode=capabilities.effective_sandbox_mode,
            network=capabilities.effective_sandbox_network,
        )
    return ResolvedProviderRead(
        kind=dispatch.resolved_provider,
        model=dispatch.model_override,
        effort=dispatch.effort_override,
        gateway_profile=dispatch.gateway_profile,
        sandbox=sandbox,
    )


def available_member_actions(
    *,
    direct_team: tuple[DirectTeamMemberRead, ...],
    capabilities: EffectiveCapabilitiesRead,
    is_task_lead: bool = False,
    state_legal_actions: frozenset[NodeOperationName] | None = None,
) -> tuple[str, ...]:
    node_kind = (
        NodeKind.ROOT if is_task_lead else NodeKind.PARENT if direct_team else NodeKind.WORKER
    )
    legal_actions = (
        set(state_legal_actions)
        if state_legal_actions is not None
        else {descriptor.name for descriptor in select_node_operation_descriptors()}
    )
    if not direct_team:
        legal_actions.difference_update(
            (
                NodeOperationName.DELEGATE,
                NodeOperationName.UPDATE_CHILD,
                NodeOperationName.REMOVE_CHILD,
            )
        )
    elif not any(member.availability is MemberAvailability.AVAILABLE for member in direct_team):
        legal_actions.discard(NodeOperationName.DELEGATE)
    return tuple(
        descriptor.name.value
        for descriptor in select_node_operation_descriptors(
            NodeOperationSelection(
                node_kind=node_kind,
                is_human_request_allowed=bool(capabilities.human_request),
                is_command_run_allowed=capabilities.command_run == "allow",
                legal_operations=legal_actions,
            )
        )
    )


async def _read_direct_team_configurations(
    session: AsyncSession,
    children: tuple[TeamRevisionMemberModel, ...],
) -> dict[ConfigurationKey, MemberConfigurationModel]:
    keys = tuple(
        (child.task_id, child.member_id, child.member_configuration_id) for child in children
    )
    configurations = tuple(
        await session.scalars(
            select(MemberConfigurationModel).where(
                tuple_(
                    MemberConfigurationModel.task_id,
                    MemberConfigurationModel.member_id,
                    MemberConfigurationModel.member_configuration_id,
                ).in_(keys)
            )
        )
    )
    return {
        (
            configuration.task_id,
            configuration.member_id,
            configuration.member_configuration_id,
        ): configuration
        for configuration in configurations
    }


async def _read_busy_direct_team_members(
    session: AsyncSession,
    children: tuple[TeamRevisionMemberModel, ...],
) -> frozenset[MemberKey]:
    member_keys = tuple((child.task_id, child.member_id) for child in children)
    rows = await session.execute(
        select(AssignmentModel.task_id, AssignmentModel.member_id).where(
            tuple_(AssignmentModel.task_id, AssignmentModel.member_id).in_(member_keys),
            AssignmentModel.terminal_outcome.is_(None),
            AssignmentModel.superseded_at.is_(None),
        )
    )
    return frozenset((task_id, member_id) for task_id, member_id in rows)


def _participation_basis(child: TeamRevisionMemberModel) -> ParticipationBasis:
    return (
        child.task_id,
        child.member_id,
        child.member_configuration_id,
        child.member_branch_basis_id,
    )


def _direct_team_member_read(
    child: TeamRevisionMemberModel,
    *,
    configuration: MemberConfigurationModel,
    capabilities: EffectiveCapabilitySet,
    provider: ProviderResolution,
    busy_members: frozenset[MemberKey],
    participating_bases: frozenset[ParticipationBasis],
) -> DirectTeamMemberRead:
    return DirectTeamMemberRead(
        id=child.member_id,
        title=configuration.title,
        description=configuration.description,
        instruction=configuration.instruction,
        provider=resolved_provider_read(provider),
        capabilities=effective_capabilities_read(capabilities),
        participation=(
            MemberParticipation.SATISFIED
            if _participation_basis(child) in participating_bases
            else MemberParticipation.REQUIRED
        ),
        availability=(
            MemberAvailability.BUSY
            if (child.task_id, child.member_id) in busy_members
            else MemberAvailability.AVAILABLE
        ),
    )


def _capability_value(value: object) -> Literal["allow", "deny"]:
    if isinstance(value, CapabilityDecision):
        return value.value
    effective = getattr(value, "effective", value)
    if isinstance(effective, CapabilityDecision):
        return effective.value
    return "allow" if str(effective) == "allow" else "deny"


__all__ = [
    "available_member_actions",
    "effective_capabilities_read",
    "persisted_provider_read",
    "read_direct_team_members",
    "resolved_provider_read",
]

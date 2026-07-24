from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowNodeModel,
)
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.contracts.primitives import (
    CapabilityDecision,
    HumanRequestKind,
)
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
    resolve_member_provider_route,
)
from banksia.runtime.team.participation import read_accepted_green_participation


async def read_direct_team_members(
    session: AsyncSession,
    *,
    children: tuple[FlowNodeModel, ...],
    dependencies: DispatchOpeningDependencies,
) -> tuple[DirectTeamMemberRead, ...]:
    """Read one current direct team from exact Flow/Team selections."""

    direct_team: list[DirectTeamMemberRead] = []
    for child in children:
        capabilities = await resolve_effective_capabilities_for_node(session, node=child)
        provider = await resolve_member_provider_route(
            session,
            task_id=child.task_id,
            member_configuration_id=child.member_configuration_id,
            settings=dependencies.settings,
            available_adapter_kinds=dependencies.available_adapter_kinds,
        )
        capabilities = narrow_provider_capabilities(
            route=provider.route,
            sandbox=provider.sandbox,
            capabilities=capabilities,
        )
        direct_team.append(
            DirectTeamMemberRead(
                id=child.member_id,
                title=child.member_title,
                description=child.description or None,
                instruction=child.node_instruction,
                provider=resolved_provider_read(provider),
                capabilities=effective_capabilities_read(capabilities),
                participation=(
                    MemberParticipation.SATISFIED
                    if await read_accepted_green_participation(
                        session,
                        task_id=child.task_id,
                        member_id=child.member_id,
                        member_configuration_id=child.member_configuration_id,
                        member_branch_basis_id=child.member_branch_basis_id,
                    )
                    else MemberParticipation.REQUIRED
                ),
                availability=(
                    MemberAvailability.AVAILABLE
                    if child.state in {"ready", "done", "failed"}
                    else MemberAvailability.BUSY
                ),
            )
        )
    return tuple(direct_team)


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
    return ResolvedProviderRead(
        kind=route.kind.value,
        gateway_profile=route.gateway_profile,
    )


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

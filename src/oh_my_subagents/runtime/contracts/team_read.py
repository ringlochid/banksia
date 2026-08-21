from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from oh_my_subagents.runtime.contracts.primitives import HumanRequestKind

TeamReadIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class _TeamReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemberBehavior(StrEnum):
    MANAGER = "manager"
    CONTRIBUTOR = "contributor"


class MemberParticipation(StrEnum):
    REQUIRED = "required"
    SATISFIED = "satisfied"


class MemberAvailability(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"


class ResolvedSandboxRead(_TeamReadModel):
    mode: TeamReadIdentifier
    network: TeamReadIdentifier


class ResolvedProviderRead(_TeamReadModel):
    kind: TeamReadIdentifier
    model: TeamReadIdentifier | None = None
    effort: TeamReadIdentifier | None = None
    gateway_profile: TeamReadIdentifier | None = None
    sandbox: ResolvedSandboxRead | None = None


class EffectiveCapabilitiesRead(_TeamReadModel):
    human_request: tuple[HumanRequestKind, ...] = ()
    command_run: Literal["allow", "deny"] = "deny"


class CurrentMemberRead(_TeamReadModel):
    id: TeamReadIdentifier
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    position: Literal["task_lead"] | None = None
    behavior: MemberBehavior
    provider: ResolvedProviderRead
    effective_capabilities: EffectiveCapabilitiesRead


class DirectTeamMemberRead(_TeamReadModel):
    id: TeamReadIdentifier
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    provider: ResolvedProviderRead
    capabilities: EffectiveCapabilitiesRead
    participation: MemberParticipation
    availability: MemberAvailability


__all__ = [
    "CurrentMemberRead",
    "DirectTeamMemberRead",
    "EffectiveCapabilitiesRead",
    "MemberAvailability",
    "MemberBehavior",
    "MemberParticipation",
    "ResolvedProviderRead",
    "ResolvedSandboxRead",
    "TeamReadIdentifier",
]

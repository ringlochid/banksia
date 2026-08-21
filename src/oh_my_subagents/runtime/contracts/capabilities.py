from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from oh_my_subagents.providers import NetworkAccess, ProviderNativeAccess
from oh_my_subagents.runtime.contracts.common import RuntimeSchemaText
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.contracts.primitives import CapabilityDecision, HumanRequestKind


class CapabilitySource(StrEnum):
    DEFAULT = "default"
    MEMBER_CONFIGURATION = "member_configuration"
    CONTROLLER = "controller"


class CapabilityCeilingSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: ProviderNativeAccess | None = None
    network_access: NetworkAccess | None = None
    allowed_human_request_kinds: tuple[HumanRequestKind, ...] | None = None
    command_run: CapabilityDecision | None = None


class EffectiveProviderNativeAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    effective: ProviderNativeAccess = ProviderNativeAccess.FULL
    source: CapabilitySource = CapabilitySource.DEFAULT


class EffectiveNetworkAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    effective: NetworkAccess = NetworkAccess.ALLOW
    source: CapabilitySource = CapabilitySource.DEFAULT


class HumanRequestCapabilitySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    direction: CapabilityDecision = CapabilityDecision.DENY
    approval: CapabilityDecision = CapabilityDecision.DENY
    input: CapabilityDecision = CapabilityDecision.DENY
    review: CapabilityDecision = CapabilityDecision.DENY


class HumanRequestCapabilitySources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    direction: CapabilitySource = CapabilitySource.DEFAULT
    approval: CapabilitySource = CapabilitySource.DEFAULT
    input: CapabilitySource = CapabilitySource.DEFAULT
    review: CapabilitySource = CapabilitySource.DEFAULT


class EffectiveCapabilitySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: EffectiveProviderNativeAccess = Field(
        default_factory=EffectiveProviderNativeAccess
    )
    network_access: EffectiveNetworkAccess = Field(default_factory=EffectiveNetworkAccess)
    requested_human_request: HumanRequestCapabilitySet = Field(
        default_factory=HumanRequestCapabilitySet
    )
    requested_human_request_source: CapabilitySource = CapabilitySource.DEFAULT
    human_request: HumanRequestCapabilitySet = Field(default_factory=HumanRequestCapabilitySet)
    human_request_sources: HumanRequestCapabilitySources = Field(
        default_factory=HumanRequestCapabilitySources
    )
    requested_command_run: CapabilityDecision = CapabilityDecision.DENY
    requested_command_run_source: CapabilitySource = CapabilitySource.DEFAULT
    command_run: CapabilityDecision = CapabilityDecision.DENY
    command_run_source: CapabilitySource = CapabilitySource.DEFAULT


class CapabilityRejectionError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    code: Literal[OperationFailureCode.CAPABILITY_REJECTED] = (
        OperationFailureCode.CAPABILITY_REJECTED
    )
    capability: RuntimeSchemaText
    message: RuntimeSchemaText
    next_legal_action: RuntimeSchemaText | None = None


__all__ = [
    "CapabilityCeilingSet",
    "CapabilityRejectionError",
    "CapabilitySource",
    "EffectiveCapabilitySet",
    "EffectiveNetworkAccess",
    "EffectiveProviderNativeAccess",
    "HumanRequestCapabilitySet",
    "HumanRequestCapabilitySources",
]

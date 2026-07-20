from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts.registry import NetworkAccess, ProviderNativeAccess
from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.contracts.primitives import CapabilityDecision


class CapabilitySource(StrEnum):
    DEFAULT = "default"
    POLICY_DEFINITION = "policy_definition"
    TASK_POLICY = "task_policy"
    CONTROLLER = "controller"


class CapabilityCeilingSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: ProviderNativeAccess | None = None
    network_access: NetworkAccess | None = None


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


class EffectiveCapabilitySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    provider_native_access: EffectiveProviderNativeAccess = Field(
        default_factory=EffectiveProviderNativeAccess
    )
    network_access: EffectiveNetworkAccess = Field(default_factory=EffectiveNetworkAccess)
    human_request: HumanRequestCapabilitySet = Field(default_factory=HumanRequestCapabilitySet)
    command_run: CapabilityDecision = CapabilityDecision.DENY


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
]

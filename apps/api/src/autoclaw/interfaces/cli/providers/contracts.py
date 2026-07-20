from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.providers import ProviderAuthenticationMethod, ProviderCheckAxisStatus


class ProviderProductStatus(StrEnum):
    MANAGED_TARGET = "managed_target"
    EXPERIMENTAL = "experimental"


class ProviderCheckOutcome(StrEnum):
    READY = "ready"
    LOCAL_PREREQUISITES_READY = "local_prerequisites_ready"
    NOT_CONFIGURED = "not_configured"
    NOT_INSTALLED = "not_installed"
    AUTHENTICATION_FAILED = "authentication_failed"
    UNREACHABLE = "unreachable"
    INCOMPATIBLE = "incompatible"
    POLICY_BLOCKED = "policy_blocked"
    CHECK_FAILED = "check_failed"


class ProviderIdentityOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NOT_INSTALLED = "not_installed"
    FAILED = "failed"


class ProviderDefinitionSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    kind: ProviderKind
    integration: str
    product_status: ProviderProductStatus
    is_integration_available: bool = Field(alias="integration_available")
    setup_owner: Literal["autoclaw", "shared", "user"]


class ProviderStatusSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    kind: ProviderKind
    product_status: ProviderProductStatus
    is_integration_available: bool = Field(alias="integration_available")
    is_configured: bool = Field(alias="configured")
    is_default: bool
    has_configuration_fields: bool = Field(alias="configuration_fields_present")
    service_identity: str
    native_home: str
    authentication: Literal["not_checked"] = "not_checked"
    reachability: Literal["not_checked"] = "not_checked"
    route: dict[str, str | bool | None]
    limitations: tuple[str, ...] = ()


class ProviderCheckSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProviderKind
    outcome: ProviderCheckOutcome
    is_ready: bool | None
    service_identity: str
    native_home: str
    authentication: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED
    authentication_method: ProviderAuthenticationMethod | None = None
    reachability: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED
    detail: str
    limitations: tuple[str, ...] = ()


class ProviderConfigurationSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    provider: ProviderKind
    is_configured: bool = Field(default=True, alias="configured")
    default_provider: ProviderKind
    is_default_changed: bool = Field(alias="default_changed")
    product_status: ProviderProductStatus


class ProviderIdentitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderKind
    action: Literal["login", "logout"]
    outcome: ProviderIdentityOutcome
    service_identity: str
    native_home: str
    authentication_method: ProviderAuthenticationMethod | None = None
    detail: str


__all__ = [
    "ProviderCheckOutcome",
    "ProviderCheckSnapshot",
    "ProviderConfigurationSnapshot",
    "ProviderDefinitionSnapshot",
    "ProviderIdentityOutcome",
    "ProviderIdentitySnapshot",
    "ProviderProductStatus",
    "ProviderStatusSnapshot",
]

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from banksia.providers import (
    ManagedExtensionMode,
    ManagedSandboxMode,
    NetworkAccess,
    ProviderKind,
)
from banksia.runtime.contracts.common import RuntimeSchemaText


class ProviderSelectionBasis(StrEnum):
    EXPLICIT = "explicit"
    DEFAULT = "default"


class ProviderRouteValueSource(StrEnum):
    MEMBER_CONFIGURATION = "member_configuration"
    PROVIDER_CONFIGURATION = "provider_configuration"


class SandboxResolutionSource(StrEnum):
    DEFAULT = "default"
    MEMBER_CONFIGURATION = "member_configuration"
    CONTROLLER = "controller"


class ExtensionModeResolutionSource(StrEnum):
    MEMBER_CONFIGURATION = "member_configuration"
    PROVIDER_CONFIGURATION = "provider_configuration"
    CONTROLLER = "controller"


class ManagedExtensionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    requested_mode: ManagedExtensionMode
    requested_source: ExtensionModeResolutionSource
    effective_mode: ManagedExtensionMode
    effective_source: ExtensionModeResolutionSource

    @model_validator(mode="after")
    def validate_narrowing(self) -> Self:
        if self.effective_source is ExtensionModeResolutionSource.CONTROLLER:
            if (
                self.requested_mode is not ManagedExtensionMode.INHERIT
                or self.effective_mode is not ManagedExtensionMode.ISOLATED
            ):
                raise ValueError("controller extension resolution may only narrow inheritance")
        elif (
            self.effective_mode is not self.requested_mode
            or self.effective_source is not self.requested_source
        ):
            raise ValueError("unchanged extension resolution must preserve mode and source")
        return self


class ManagedSandboxResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    requested_mode: ManagedSandboxMode
    requested_network: NetworkAccess
    requested_source: SandboxResolutionSource
    effective_mode: ManagedSandboxMode
    effective_network: NetworkAccess
    effective_mode_source: SandboxResolutionSource
    effective_network_source: SandboxResolutionSource


class CodexProviderRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: Literal[ProviderKind.CODEX]
    model_override: RuntimeSchemaText | None = None
    effort_override: RuntimeSchemaText | None = None


class ClaudeProviderRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: Literal[ProviderKind.CLAUDE]
    model_override: RuntimeSchemaText | None = None
    effort_override: RuntimeSchemaText | None = None


type ProviderRoute = Annotated[
    CodexProviderRoute | ClaudeProviderRoute,
    Field(discriminator="kind"),
]


class ProviderResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    requested_provider: ProviderKind
    resolved_provider: ProviderKind
    selection_basis: ProviderSelectionBasis
    route: ProviderRoute
    sandbox: ManagedSandboxResolution | None
    extensions: ManagedExtensionResolution | None
    model_source: ProviderRouteValueSource | None
    effort_source: ProviderRouteValueSource | None

    @model_validator(mode="after")
    def validate_exact_route(self) -> Self:
        if self.requested_provider != self.resolved_provider:
            raise ValueError("requested_provider must equal resolved_provider")
        if self.route.kind != self.resolved_provider:
            raise ValueError("route.kind must equal resolved_provider")
        if self.sandbox is None or self.extensions is None:
            raise ValueError("managed providers require exact sandbox and extension resolution")
        if not isinstance(self.route, CodexProviderRoute | ClaudeProviderRoute):
            raise ValueError("managed provider requires a managed provider route")
        if self.model_source is None or self.effort_source is None:
            raise ValueError("managed providers require exact model and effort sources")
        if (
            self.model_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
            and self.route.model_override is None
        ):
            raise ValueError("authored model source requires an authored model value")
        if (
            self.effort_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
            and self.route.effort_override is None
        ):
            raise ValueError("authored effort source requires an authored effort value")
        if self.selection_basis is ProviderSelectionBasis.DEFAULT and (
            self.model_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
            or self.effort_source is ProviderRouteValueSource.MEMBER_CONFIGURATION
            or self.extensions.requested_source
            is ExtensionModeResolutionSource.MEMBER_CONFIGURATION
        ):
            raise ValueError("default provider selection has no Member field overrides")
        return self


__all__ = [
    "ClaudeProviderRoute",
    "CodexProviderRoute",
    "ExtensionModeResolutionSource",
    "ManagedExtensionResolution",
    "ManagedSandboxResolution",
    "ProviderResolution",
    "ProviderRoute",
    "ProviderRouteValueSource",
    "ProviderSelectionBasis",
    "SandboxResolutionSource",
]

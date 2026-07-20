from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.contracts.common import RuntimeSchemaText


class ProviderSelectionBasis(StrEnum):
    EXPLICIT = "explicit"
    DEFAULT = "default"


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


class OpenClawProviderRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: Literal[ProviderKind.OPENCLAW]
    gateway_profile: RuntimeSchemaText


type ProviderRoute = Annotated[
    CodexProviderRoute | ClaudeProviderRoute | OpenClawProviderRoute,
    Field(discriminator="kind"),
]


class ProviderResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    requested_provider: ProviderKind
    resolved_provider: ProviderKind
    selection_basis: ProviderSelectionBasis
    route: ProviderRoute

    @model_validator(mode="after")
    def validate_exact_route(self) -> Self:
        if self.requested_provider != self.resolved_provider:
            raise ValueError("requested_provider must equal resolved_provider")
        if self.route.kind != self.resolved_provider:
            raise ValueError("route.kind must equal resolved_provider")
        return self


__all__ = [
    "ClaudeProviderRoute",
    "CodexProviderRoute",
    "OpenClawProviderRoute",
    "ProviderResolution",
    "ProviderRoute",
    "ProviderSelectionBasis",
]

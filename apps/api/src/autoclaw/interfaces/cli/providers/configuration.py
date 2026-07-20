from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from autoclaw.config import (
    ClaudeSettings,
    CodexSettings,
    OpenClawGatewayAuthMode,
    OpenClawSettings,
    RuntimeSettings,
    Settings,
)
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.bootstrap.config import (
    ConfigSections,
    persist_config_mutation,
)
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderConfigurationSnapshot,
    ProviderProductStatus,
)
from autoclaw.runtime.providers import provider_selection_from_kind, resolve_provider_route


class ProviderConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderKind
    model: str | None = None
    effort: str | None = None
    cli_path: str | None = None
    gateway_url: str | None = None
    gateway_profile: str | None = None
    gateway_auth_mode: OpenClawGatewayAuthMode | None = None

    @model_validator(mode="after")
    def validate_provider_fields(self) -> ProviderConfigurationRequest:
        if self.provider == ProviderKind.OPENCLAW:
            if self.model is not None or self.effort is not None:
                raise ValueError("OpenClaw configuration does not accept model or effort")
            return self
        if (
            self.cli_path is not None
            or self.gateway_url is not None
            or self.gateway_profile is not None
            or self.gateway_auth_mode is not None
        ):
            raise ValueError(f"{self.provider.value} configuration does not accept Gateway fields")
        return self


def configure_provider(
    config_path: Path,
    request: ProviderConfigurationRequest,
) -> ProviderConfigurationSnapshot:
    default_changed = False

    def build_candidate(payload: ConfigSections) -> ConfigSections:
        nonlocal default_changed
        provider_section = dict(payload.get(request.provider.value, {}))
        provider_section["enabled"] = True
        update_provider_route_section(provider_section, request)
        payload[request.provider.value] = provider_section

        runtime_section = dict(payload.get("runtime", {}))
        if not runtime_section.get("default_provider"):
            runtime_section["default_provider"] = request.provider.value
            default_changed = True
        payload["runtime"] = runtime_section
        validate_provider_config(payload, requested_provider=request.provider)
        return payload

    sections = persist_config_mutation(config_path, build_candidate)
    default_provider = ProviderKind(sections["runtime"]["default_provider"])
    return ProviderConfigurationSnapshot.model_validate(
        {
            "provider": request.provider,
            "default_provider": default_provider,
            "default_changed": default_changed,
            "product_status": product_status_for(request.provider),
        }
    )


def set_default_provider(
    config_path: Path,
    provider: ProviderKind,
) -> ProviderConfigurationSnapshot:
    previous_default: ProviderKind | None = None

    def build_candidate(payload: ConfigSections) -> ConfigSections:
        nonlocal previous_default
        runtime_section = dict(payload.get("runtime", {}))
        raw_previous = runtime_section.get("default_provider")
        previous_default = ProviderKind(raw_previous) if raw_previous else None
        runtime_section["default_provider"] = provider.value
        payload["runtime"] = runtime_section
        validate_provider_config(payload, requested_provider=provider)
        return payload

    persist_config_mutation(config_path, build_candidate)
    return ProviderConfigurationSnapshot.model_validate(
        {
            "provider": provider,
            "default_provider": provider,
            "default_changed": previous_default != provider,
            "product_status": product_status_for(provider),
        }
    )


def set_openclaw_gateway_auth_mode(
    config_path: Path,
    mode: OpenClawGatewayAuthMode,
) -> None:
    def build_candidate(payload: ConfigSections) -> ConfigSections:
        provider_section = dict(payload.get(ProviderKind.OPENCLAW.value, {}))
        provider_section["gateway_auth_mode"] = mode.value
        payload[ProviderKind.OPENCLAW.value] = provider_section
        validate_provider_config(payload, requested_provider=ProviderKind.OPENCLAW)
        return payload

    persist_config_mutation(config_path, build_candidate)


def update_provider_route_section(
    section: dict[str, object],
    request: ProviderConfigurationRequest,
) -> None:
    if request.provider in {ProviderKind.CODEX, ProviderKind.CLAUDE}:
        if request.model is not None:
            section["model"] = request.model
        if request.effort is not None:
            section["effort"] = request.effort
        return

    if request.cli_path is not None:
        section["cli_path"] = _resolved_executable(request.cli_path)
    elif "cli_path" not in section:
        section["cli_path"] = _resolved_executable(OpenClawSettings().cli_path)
    if request.gateway_url is not None:
        section["gateway_url"] = request.gateway_url
    section.setdefault("gateway_url", OpenClawSettings().gateway_url)
    if request.gateway_profile is not None:
        section["gateway_profile"] = request.gateway_profile
    section.setdefault("gateway_profile", OpenClawSettings().gateway_profile)
    if request.gateway_auth_mode is not None:
        section["gateway_auth_mode"] = request.gateway_auth_mode.value
    section.setdefault("gateway_auth_mode", OpenClawSettings().gateway_auth_mode.value)


def _resolved_executable(value: str) -> str:
    resolved = shutil.which(value)
    return str(Path(resolved).resolve()) if resolved is not None else value


def validate_provider_config(
    payload: ConfigSections,
    *,
    requested_provider: ProviderKind,
) -> None:
    settings = settings_from_config_sections(payload)
    resolve_provider_route(
        provider=provider_selection_from_kind(requested_provider),
        settings=settings,
        available_adapter_kinds=set(ProviderKind),
    )
    if settings.runtime.default_provider is not None:
        resolve_provider_route(
            provider=None,
            settings=settings,
            available_adapter_kinds=set(ProviderKind),
        )


def settings_from_config_sections(payload: ConfigSections) -> Settings:
    return Settings.model_validate(
        {
            "codex": CodexSettings.model_validate(payload.get("codex", {})),
            "claude": ClaudeSettings.model_validate(payload.get("claude", {})),
            "openclaw": OpenClawSettings.model_validate(payload.get("openclaw", {})),
            "runtime": RuntimeSettings.model_validate(payload.get("runtime", {})),
        }
    )


def product_status_for(provider: ProviderKind) -> ProviderProductStatus:
    if provider == ProviderKind.OPENCLAW:
        return ProviderProductStatus.EXPERIMENTAL
    return ProviderProductStatus.MANAGED_TARGET


__all__ = [
    "ProviderConfigurationRequest",
    "configure_provider",
    "product_status_for",
    "set_default_provider",
    "set_openclaw_gateway_auth_mode",
    "settings_from_config_sections",
    "update_provider_route_section",
    "validate_provider_config",
]

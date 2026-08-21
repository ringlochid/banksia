from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from oh_my_subagents.config import (
    ClaudeSettings,
    CodexSettings,
    OperatorSettings,
    RuntimeSettings,
    Settings,
)
from oh_my_subagents.interfaces.cli.bootstrap.config import (
    ConfigSections,
    persist_config_mutation,
)
from oh_my_subagents.interfaces.cli.providers.contracts import (
    ProviderConfigurationSnapshot,
    ProviderProductStatus,
)
from oh_my_subagents.providers import ACTIVE_PROVIDER_KINDS, ManagedExtensionMode, ProviderKind
from oh_my_subagents.runtime.providers import provider_selection_from_kind, resolve_provider_route


class ProviderConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderKind
    model: str | None = None
    effort: str | None = None
    extension_mode: ManagedExtensionMode | None = None

    @model_validator(mode="after")
    def require_active_provider(self) -> ProviderConfigurationRequest:
        if self.provider not in ACTIVE_PROVIDER_KINDS:
            raise ValueError("OpenClaw is retired; configure Codex or Claude")
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
        if runtime_section.get("default_provider") in {None, ProviderKind.OPENCLAW.value}:
            runtime_section["default_provider"] = request.provider.value
            default_changed = True
        payload["runtime"] = runtime_section
        payload.pop(ProviderKind.OPENCLAW.value, None)
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
        if provider not in ACTIVE_PROVIDER_KINDS:
            raise ValueError("OpenClaw is retired; select Codex or Claude")
        runtime_section = dict(payload.get("runtime", {}))
        raw_previous = runtime_section.get("default_provider")
        previous_default = ProviderKind(raw_previous) if raw_previous else None
        runtime_section["default_provider"] = provider.value
        payload["runtime"] = runtime_section
        payload.pop(ProviderKind.OPENCLAW.value, None)
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


def update_provider_route_section(
    section: dict[str, object],
    request: ProviderConfigurationRequest,
) -> None:
    if request.model is not None:
        section["model"] = request.model
    if request.effort is not None:
        section["effort"] = request.effort
    if request.extension_mode is not None:
        section["extension_mode"] = request.extension_mode.value


def validate_provider_config(
    payload: ConfigSections,
    *,
    requested_provider: ProviderKind,
) -> None:
    settings = settings_from_config_sections(payload)
    resolve_provider_route(
        provider=provider_selection_from_kind(requested_provider),
        settings=settings,
        available_adapter_kinds=ACTIVE_PROVIDER_KINDS,
    )
    if settings.runtime.default_provider is not None:
        resolve_provider_route(
            provider=None,
            settings=settings,
            available_adapter_kinds=ACTIVE_PROVIDER_KINDS,
        )


def settings_from_config_sections(payload: ConfigSections) -> Settings:
    return Settings.model_validate(
        {
            "codex": CodexSettings.model_validate(payload.get("codex", {})),
            "claude": ClaudeSettings.model_validate(payload.get("claude", {})),
            "operator": OperatorSettings.model_validate(payload.get("operator", {})),
            "runtime": RuntimeSettings.model_validate(payload.get("runtime", {})),
        }
    )


def product_status_for(provider: ProviderKind) -> ProviderProductStatus:
    if provider not in ACTIVE_PROVIDER_KINDS:
        raise ValueError("OpenClaw is retired; select Codex or Claude")
    return ProviderProductStatus.MANAGED_TARGET


__all__ = [
    "ProviderConfigurationRequest",
    "configure_provider",
    "product_status_for",
    "set_default_provider",
    "settings_from_config_sections",
    "update_provider_route_section",
    "validate_provider_config",
]

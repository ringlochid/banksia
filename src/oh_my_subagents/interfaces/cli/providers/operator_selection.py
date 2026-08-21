from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from oh_my_subagents.config import (
    OperatorProvider,
    OperatorSettings,
    Settings,
    load_settings,
)
from oh_my_subagents.interfaces.cli.bootstrap.config import (
    ConfigSections,
    persist_config_mutation,
    read_config_sections,
)
from oh_my_subagents.interfaces.cli.providers.configuration import settings_from_config_sections
from oh_my_subagents.interfaces.cli.support import command_env


class OperatorSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: OperatorProvider
    model: str | None = None
    effort: str | None = None

    def operator_settings(self) -> OperatorSettings:
        return OperatorSettings(
            provider=self.provider,
            model=self.model,
            effort=self.effort,
        )


class OperatorSelectionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persisted: OperatorSettings
    effective: OperatorSettings
    is_environment_override: bool
    is_provider_route_configured: bool
    next_action: str


class OperatorSelectionMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selection: OperatorSelectionSnapshot
    is_changed: bool


class OperatorProviderRouteNotConfiguredError(ValueError):
    """Raised when Operator selects a managed provider without a saved route."""

    def __init__(self, provider: OperatorProvider) -> None:
        self.provider = provider
        super().__init__(
            f"{provider.value.title()} must be configured before it can be selected for Operator"
        )


def save_operator_selection(
    config_path: Path,
    request: OperatorSelectionRequest,
) -> OperatorSelectionMutationResult:
    """Atomically replace the persisted Operator provider and optional overrides."""

    is_changed = False
    requested_settings = request.operator_settings()

    def build_candidate(payload: ConfigSections) -> ConfigSections:
        nonlocal is_changed
        _require_persisted_provider_route(payload, request.provider)
        previous_settings = OperatorSettings.model_validate(payload.get("operator", {}))
        operator_section = requested_settings.model_dump(
            mode="json",
            exclude_none=True,
        )
        payload["operator"] = operator_section
        settings_from_config_sections(payload)
        is_changed = previous_settings != requested_settings
        return payload

    persist_config_mutation(config_path, build_candidate)
    return OperatorSelectionMutationResult(
        selection=read_operator_selection(config_path),
        is_changed=is_changed,
    )


def disable_operator_selection(config_path: Path) -> OperatorSelectionMutationResult:
    """Remove only the persisted Operator selection and retain provider routes."""

    is_changed = False

    def build_candidate(payload: ConfigSections) -> ConfigSections:
        nonlocal is_changed
        is_changed = "operator" in payload
        payload.pop("operator", None)
        settings_from_config_sections(payload)
        return payload

    persist_config_mutation(config_path, build_candidate)
    return OperatorSelectionMutationResult(
        selection=read_operator_selection(config_path),
        is_changed=is_changed,
    )


def read_operator_selection(config_path: Path) -> OperatorSelectionSnapshot:
    """Read persisted and effective Operator configuration without a provider call."""

    sections = read_config_sections(config_path)
    persisted = OperatorSettings.model_validate(sections.get("operator", {}))
    with command_env(config_path=config_path):
        settings = load_settings()
    effective = OperatorSettings.model_validate(
        settings.operator.model_dump(mode="json"),
    )
    is_route_configured = _is_effective_provider_route_configured(settings)
    return OperatorSelectionSnapshot(
        persisted=persisted,
        effective=effective,
        is_environment_override=effective != persisted,
        is_provider_route_configured=is_route_configured,
        next_action=_next_operator_action(effective, is_route_configured),
    )


def is_operator_provider_persisted(
    config_path: Path,
    provider: OperatorProvider,
) -> bool:
    """Return whether one managed provider route is enabled in the TOML file."""

    return read_config_sections(config_path).get(provider.value, {}).get("enabled") is True


def _require_persisted_provider_route(
    payload: ConfigSections,
    provider: OperatorProvider,
) -> None:
    if payload.get(provider.value, {}).get("enabled") is not True:
        raise OperatorProviderRouteNotConfiguredError(provider)


def _is_effective_provider_route_configured(settings: Settings) -> bool:
    provider = settings.operator.provider
    provider_value = provider.value if provider is not None else None
    if provider_value == OperatorProvider.CODEX.value:
        return settings.codex.enabled
    if provider_value == OperatorProvider.CLAUDE.value:
        return settings.claude.enabled
    return False


def _next_operator_action(
    effective: OperatorSettings,
    is_route_configured: bool,
) -> str:
    if effective.provider is None:
        return "oms operator setup"
    if not is_route_configured:
        return f"oms providers configure {effective.provider.value}"
    return f"oms providers check {effective.provider.value}"


__all__ = [
    "OperatorProviderRouteNotConfiguredError",
    "OperatorSelectionMutationResult",
    "OperatorSelectionRequest",
    "OperatorSelectionSnapshot",
    "disable_operator_selection",
    "is_operator_provider_persisted",
    "read_operator_selection",
    "save_operator_selection",
]

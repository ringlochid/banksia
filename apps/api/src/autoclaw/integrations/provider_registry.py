from __future__ import annotations

from autoclaw.config import Settings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.integrations.claude import ClaudeAdapter
from autoclaw.integrations.codex import CodexAdapter
from autoclaw.integrations.openclaw import build_openclaw_gateway_adapter
from autoclaw.runtime.providers.contracts import ProviderAdapter
from autoclaw.runtime.providers.registry import ProviderAdapterRegistry


def build_provider_adapter_registry(settings: Settings) -> ProviderAdapterRegistry:
    """Build the complete isolated provider registry for application lifespan."""

    return ProviderAdapterRegistry(
        build_provider_adapter(provider, settings) for provider in ProviderKind
    )


def build_provider_adapter(
    provider: ProviderKind,
    settings: Settings,
) -> ProviderAdapter:
    """Build one provider adapter from the shared runtime settings source."""

    match provider:
        case ProviderKind.CODEX:
            return CodexAdapter()
        case ProviderKind.CLAUDE:
            return ClaudeAdapter()
        case ProviderKind.OPENCLAW:
            return build_openclaw_gateway_adapter(settings)


__all__ = ["build_provider_adapter", "build_provider_adapter_registry"]

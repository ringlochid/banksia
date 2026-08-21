from __future__ import annotations

from oh_my_subagents.config import Settings
from oh_my_subagents.integrations.claude import ClaudeAdapter
from oh_my_subagents.integrations.codex import CodexAdapter
from oh_my_subagents.providers import ACTIVE_PROVIDER_KINDS, ProviderKind
from oh_my_subagents.runtime.providers.contracts import ProviderAdapter
from oh_my_subagents.runtime.providers.registry import ProviderAdapterRegistry


def build_provider_adapter_registry(settings: Settings) -> ProviderAdapterRegistry:
    """Build the complete isolated provider registry for application lifespan."""

    return ProviderAdapterRegistry(
        build_provider_adapter(provider, settings) for provider in ACTIVE_PROVIDER_KINDS
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
            raise ValueError("OpenClaw is retired and has no Oh My Subagents provider adapter")


__all__ = ["build_provider_adapter", "build_provider_adapter_registry"]

from __future__ import annotations

from typing import cast

from fastapi import Request

from oh_my_subagents.operator import OperatorConversationService
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.post_commit import RuntimeEffectPublisher
from oh_my_subagents.runtime.providers import ProviderAdapterRegistry

LOCAL_OPERATOR_ACTOR_REF = "local_operator"


async def read_control_actor_ref() -> str:
    """Return stable provenance for the locally admitted operator surface."""
    return LOCAL_OPERATOR_ACTOR_REF


async def read_runtime_effect_publisher(request: Request) -> RuntimeEffectPublisher | None:
    return cast(
        RuntimeEffectPublisher | None,
        getattr(request.app.state, "runtime_effect_publisher", None),
    )


async def read_dispatch_opening_dependencies(request: Request) -> DispatchOpeningDependencies:
    dependencies = getattr(request.app.state, "dispatch_opening_dependencies", None)
    if not isinstance(dependencies, DispatchOpeningDependencies):
        raise RuntimeError("dispatch opening dependencies are unavailable")
    return dependencies


async def read_operator_conversation_service(request: Request) -> OperatorConversationService:
    service = getattr(request.app.state, "operator_conversation_service", None)
    if not isinstance(service, OperatorConversationService):
        raise RuntimeError("Operator conversation service is unavailable")
    return service


async def read_provider_adapter_registry(request: Request) -> ProviderAdapterRegistry:
    registry = getattr(request.app.state, "provider_adapter_registry", None)
    if not isinstance(registry, ProviderAdapterRegistry):
        raise RuntimeError("provider adapter registry is unavailable")
    return registry

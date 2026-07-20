from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from autoclaw.config import Settings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.prompt import DispatchRequestRenderInput
from autoclaw.runtime.contracts.provider_resolution import ProviderResolution
from autoclaw.runtime.dispatch.request_pair import (
    DispatchRequestPairRefs,
    publish_dispatch_request_pair,
)
from autoclaw.runtime.post_commit import RuntimeEffectPublisher
from autoclaw.runtime.prompt import render_dispatch_request
from autoclaw.runtime.providers.resolution import validate_provider_execution_policy


class DispatchRequestPairPublisher(Protocol):
    def __call__(
        self,
        *,
        paths: TaskRootPaths,
        dispatch_id: str,
        instructions_bytes: bytes,
        input_bytes: bytes,
    ) -> DispatchRequestPairRefs: ...


@dataclass(frozen=True, slots=True)
class DispatchOpeningDependencies:
    settings: Settings
    available_adapter_kinds: frozenset[ProviderKind]
    clock: Callable[[], datetime]
    request_pair_publisher: DispatchRequestPairPublisher
    post_commit_publisher: RuntimeEffectPublisher

    @classmethod
    def create(
        cls,
        *,
        settings: Settings,
        available_adapter_kinds: Collection[ProviderKind],
        post_commit_publisher: RuntimeEffectPublisher,
        clock: Callable[[], datetime] = utc_now,
        request_pair_publisher: DispatchRequestPairPublisher = publish_dispatch_request_pair,
    ) -> DispatchOpeningDependencies:
        return cls(
            settings=settings.model_copy(deep=True),
            available_adapter_kinds=frozenset(available_adapter_kinds),
            clock=clock,
            request_pair_publisher=request_pair_publisher,
            post_commit_publisher=post_commit_publisher,
        )


@dataclass(frozen=True, slots=True)
class PreparedDispatchRequest:
    dispatch_id: str
    due_at: datetime
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    refs: DispatchRequestPairRefs


def prepare_dispatch_request(
    *,
    dependencies: DispatchOpeningDependencies,
    paths: TaskRootPaths,
    dispatch_id: str,
    due_at: datetime,
    provider: ProviderResolution,
    capabilities: EffectiveCapabilitySet,
    request: DispatchRequestRenderInput,
) -> PreparedDispatchRequest:
    validate_provider_execution_policy(
        route=provider.route,
        provider_native_access=capabilities.provider_native_access.effective,
        network_access=capabilities.network_access.effective,
    )
    rendered = render_dispatch_request(request)
    refs = dependencies.request_pair_publisher(
        paths=paths,
        dispatch_id=dispatch_id,
        instructions_bytes=rendered.instructions_text.encode("utf-8"),
        input_bytes=rendered.input_text.encode("utf-8"),
    )
    return PreparedDispatchRequest(
        dispatch_id=dispatch_id,
        due_at=due_at,
        provider=provider,
        capabilities=capabilities,
        refs=refs,
    )


__all__ = [
    "DispatchOpeningDependencies",
    "DispatchRequestPairPublisher",
    "PreparedDispatchRequest",
    "prepare_dispatch_request",
]

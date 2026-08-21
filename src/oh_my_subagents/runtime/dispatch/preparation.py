from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime

from oh_my_subagents.config import Settings
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.contracts.capabilities import EffectiveCapabilitySet
from oh_my_subagents.runtime.contracts.prompt import DispatchRequestRenderInput
from oh_my_subagents.runtime.contracts.provider_resolution import ProviderResolution
from oh_my_subagents.runtime.contracts.text import normalize_exact_text
from oh_my_subagents.runtime.post_commit import RuntimeEffectPublisher
from oh_my_subagents.runtime.prompt import render_dispatch_request
from oh_my_subagents.runtime.providers.resolution import validate_provider_execution_configuration
from oh_my_subagents.runtime.workspace.coordination import TaskWorkspaceAdmissionCoordinator


@dataclass(frozen=True, slots=True)
class DispatchOpeningDependencies:
    settings: Settings
    available_adapter_kinds: frozenset[ProviderKind]
    clock: Callable[[], datetime]
    post_commit_publisher: RuntimeEffectPublisher
    workspace_admission_coordinator: TaskWorkspaceAdmissionCoordinator

    @classmethod
    def create(
        cls,
        *,
        settings: Settings,
        available_adapter_kinds: Collection[ProviderKind],
        post_commit_publisher: RuntimeEffectPublisher,
        clock: Callable[[], datetime] = utc_now,
        workspace_admission_coordinator: TaskWorkspaceAdmissionCoordinator | None = None,
    ) -> DispatchOpeningDependencies:
        return cls(
            settings=settings.model_copy(deep=True),
            available_adapter_kinds=frozenset(available_adapter_kinds),
            clock=clock,
            post_commit_publisher=post_commit_publisher,
            workspace_admission_coordinator=(
                workspace_admission_coordinator or TaskWorkspaceAdmissionCoordinator()
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedDispatchRequest:
    dispatch_id: str
    due_at: datetime
    provider: ProviderResolution
    capabilities: EffectiveCapabilitySet
    instructions: str
    input: str


def prepare_dispatch_request(
    *,
    dependencies: DispatchOpeningDependencies,
    dispatch_id: str,
    due_at: datetime,
    provider: ProviderResolution,
    capabilities: EffectiveCapabilitySet,
    request: DispatchRequestRenderInput,
) -> PreparedDispatchRequest:
    validate_provider_execution_configuration(
        route=provider.route,
        provider_native_access=capabilities.provider_native_access.effective,
        network_access=capabilities.network_access.effective,
        sandbox_mode=(provider.sandbox.effective_mode if provider.sandbox is not None else None),
    )
    rendered = render_dispatch_request(request)
    return PreparedDispatchRequest(
        dispatch_id=dispatch_id,
        due_at=due_at,
        provider=provider,
        capabilities=capabilities,
        instructions=normalize_exact_text(
            rendered.instructions_text,
            label="dispatch instructions",
            is_nonblank_required=True,
        ),
        input=normalize_exact_text(
            rendered.input_text,
            label="dispatch input",
            is_nonblank_required=True,
        ),
    )


__all__ = [
    "DispatchOpeningDependencies",
    "PreparedDispatchRequest",
    "prepare_dispatch_request",
]

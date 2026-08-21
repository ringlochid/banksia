from __future__ import annotations

from oh_my_subagents.config import Settings
from oh_my_subagents.operator.conversation_reads import OperatorSessionFactory
from oh_my_subagents.operator.tools.contracts import OperatorTool
from oh_my_subagents.operator.tools.runtime import build_runtime_operator_tools
from oh_my_subagents.operator.tools.workflows import build_workflow_operator_tools
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.providers import ProviderAdapterRegistry


def build_operator_tools(
    *,
    settings: Settings,
    session_factory: OperatorSessionFactory,
    dispatch_dependencies: DispatchOpeningDependencies,
    provider_adapters: ProviderAdapterRegistry | None = None,
) -> tuple[OperatorTool, ...]:
    """Bind the exact ordered Oh My Subagents Operator catalog to product-service leaves."""

    return (
        *build_workflow_operator_tools(
            settings=settings,
            session_factory=session_factory,
        ),
        *build_runtime_operator_tools(
            settings=settings,
            session_factory=session_factory,
            dispatch_dependencies=dispatch_dependencies,
            provider_adapters=provider_adapters or ProviderAdapterRegistry(()),
        ),
    )


__all__ = ["build_operator_tools"]

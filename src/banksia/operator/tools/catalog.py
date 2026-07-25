from __future__ import annotations

from banksia.config import Settings
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.tools.contracts import OperatorTool
from banksia.operator.tools.runtime import build_runtime_operator_tools
from banksia.operator.tools.workflows import build_workflow_operator_tools
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies


def build_operator_tools(
    *,
    settings: Settings,
    session_factory: OperatorSessionFactory,
    dispatch_dependencies: DispatchOpeningDependencies,
) -> tuple[OperatorTool, ...]:
    """Bind the exact ordered Banksia Operator catalog to product-service leaves."""

    return (
        *build_workflow_operator_tools(
            settings=settings,
            session_factory=session_factory,
        ),
        *build_runtime_operator_tools(
            settings=settings,
            session_factory=session_factory,
            dispatch_dependencies=dispatch_dependencies,
        ),
    )


__all__ = ["build_operator_tools"]

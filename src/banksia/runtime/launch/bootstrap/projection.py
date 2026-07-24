from __future__ import annotations

from banksia.runtime.contracts import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from banksia.runtime.projection.signals import SupportProjectionSignal
from banksia.runtime.task_root import resolve_task_root_paths


def build_launch_bootstrap_result(
    bootstrap_input: RuntimeBootstrapInput,
) -> RuntimeBootstrapResult:
    """Build fresh-task controller records without opening or projecting a dispatch."""

    task_root_paths = resolve_task_root_paths(
        task_root=bootstrap_input.task_root,
        workspace=bootstrap_input.workspace,
    )
    return RuntimeBootstrapResult(
        paths=task_root_paths,
        assignment=bootstrap_input.assignment,
    )


def build_launch_support_projection_signals(
    bootstrap_input: RuntimeBootstrapInput,
) -> tuple[SupportProjectionSignal, ...]:
    """Expose post-commit launch projections without coupling launch to the owner."""

    del bootstrap_input
    return ()


__all__ = ["build_launch_bootstrap_result", "build_launch_support_projection_signals"]

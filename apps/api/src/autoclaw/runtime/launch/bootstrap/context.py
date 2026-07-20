from __future__ import annotations

from dataclasses import dataclass

from autoclaw.runtime.contracts import RuntimeBootstrapInput
from autoclaw.runtime.ids import compiled_plan_id_for_task, flow_id_for_task


@dataclass(frozen=True)
class LaunchBootstrapPersistenceContext:
    compiled_plan_id: str
    flow_id: str
    workspace_binding_mode: str


def build_launch_bootstrap_persistence_context(
    *,
    bootstrap_input: RuntimeBootstrapInput,
) -> LaunchBootstrapPersistenceContext:
    roots = bootstrap_input.task_compose.roots
    workspace_binding_mode = (
        roots.workspace.mode.value
        if roots is not None and roots.workspace is not None
        else "ensure_task_default"
    )
    return LaunchBootstrapPersistenceContext(
        compiled_plan_id=compiled_plan_id_for_task(bootstrap_input.task_id),
        flow_id=flow_id_for_task(bootstrap_input.task_id),
        workspace_binding_mode=workspace_binding_mode,
    )

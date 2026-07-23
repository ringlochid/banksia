from __future__ import annotations

from dataclasses import dataclass

from banksia.runtime.contracts import RuntimeBootstrapInput
from banksia.runtime.ids import compiled_plan_id_for_task, flow_id_for_task


@dataclass(frozen=True)
class LaunchBootstrapPersistenceContext:
    compiled_plan_id: str
    flow_id: str


def build_launch_bootstrap_persistence_context(
    *,
    bootstrap_input: RuntimeBootstrapInput,
) -> LaunchBootstrapPersistenceContext:
    return LaunchBootstrapPersistenceContext(
        compiled_plan_id=compiled_plan_id_for_task(bootstrap_input.task_id),
        flow_id=flow_id_for_task(bootstrap_input.task_id),
    )

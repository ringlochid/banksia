from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.registry import compile_current_workflow_launch_snapshot
from autoclaw.runtime import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
    RuntimeLaunchInput,
)
from autoclaw.runtime.contracts import TaskEventSource, TaskEventType
from autoclaw.runtime.ids import (
    assignment_key_for_task,
    attempt_id_for_task,
    compiled_plan_id_for_task,
    flow_id_for_task,
    flow_revision_id,
)
from autoclaw.runtime.launch.bootstrap import build_launch_support_projection_signals
from autoclaw.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from autoclaw.runtime.projection.signals import SupportProjectionSignal
from autoclaw.runtime.task_events import append_task_event


@dataclass(frozen=True, slots=True)
class StagedRuntimeLaunch:
    """Controller rows and exact support hints staged by one task launch."""

    bootstrap: RuntimeBootstrapResult
    support_projection_signals: tuple[SupportProjectionSignal, ...]


async def launch_task_runtime(
    session: AsyncSession,
    launch_input: RuntimeLaunchInput,
) -> StagedRuntimeLaunch:
    """Stage task, flow, assignment, attempt, and durable root-source truth."""

    snapshot = await compile_current_workflow_launch_snapshot(
        session,
        workflow_key=launch_input.task_compose.workflow.key,
        compiler_version=launch_input.compiler_version,
    )
    root_node_key = snapshot.workflow.definition.root.node_key
    bootstrap_input = RuntimeBootstrapInput(
        task_id=launch_input.task_id,
        active_flow_revision_id=flow_revision_id(flow_id_for_task(launch_input.task_id), 1),
        attempt_id=attempt_id_for_task(launch_input.task_id, root_node_key, 1),
        assignment_key=assignment_key_for_task(launch_input.task_id, root_node_key, 1),
        task_root=launch_input.task_root,
        task_compose=launch_input.task_compose,
        workflow_definition=snapshot.workflow.definition,
        compiled_plan=snapshot.compiled_plan,
        role_policy_lookup=snapshot.role_policy_lookup,
    )
    bootstrap = await persist_bootstrap_runtime_from_precomputed(
        session,
        bootstrap_input,
        should_commit=False,
    )
    flow_id = flow_id_for_task(launch_input.task_id)
    active_flow_revision_id = flow_revision_id(flow_id, 1)
    await append_task_event(
        session,
        task_id=launch_input.task_id,
        event_type=TaskEventType.TASK_STARTED,
        event_source=TaskEventSource.CONTROLLER,
        flow_revision_id=active_flow_revision_id,
        node_key=root_node_key,
        payload={
            "flow_id": flow_id,
            "compiled_plan_id": compiled_plan_id_for_task(launch_input.task_id),
            "workflow_key": snapshot.compiled_plan.workflow_key,
            "workflow_revision_no": snapshot.compiled_plan.definition_revision_no,
            "manifest_ref": "_runtime/workflow-manifest.md",
        },
    )
    return StagedRuntimeLaunch(
        bootstrap=bootstrap,
        support_projection_signals=build_launch_support_projection_signals(bootstrap_input),
    )


__all__ = ["StagedRuntimeLaunch", "launch_task_runtime"]

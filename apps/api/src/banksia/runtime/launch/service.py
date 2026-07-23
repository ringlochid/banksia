from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
    RuntimeLaunchInput,
)
from banksia.runtime.contracts import TaskEventSource, TaskEventType
from banksia.runtime.ids import (
    assignment_key_for_task,
    attempt_id_for_task,
    compiled_plan_id_for_task,
    flow_id_for_task,
    flow_revision_id,
)
from banksia.runtime.launch.bootstrap import build_launch_support_projection_signals
from banksia.runtime.launch.legacy_team_adapter import project_legacy_team_plan
from banksia.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from banksia.runtime.projection.signals import SupportProjectionSignal
from banksia.runtime.task_events import append_task_event
from banksia.runtime.team import plan_initial_task_team


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

    workflow_revision = launch_input.workflow_revision
    initial_team = plan_initial_task_team(workflow_revision, launch_input.task_id)
    legacy_plan = project_legacy_team_plan(workflow_revision, initial_team)
    root_node_key = initial_team.root_member_id
    bootstrap_input = RuntimeBootstrapInput(
        task_id=launch_input.task_id,
        active_flow_revision_id=flow_revision_id(flow_id_for_task(launch_input.task_id), 1),
        attempt_id=attempt_id_for_task(launch_input.task_id, root_node_key, 1),
        assignment_key=assignment_key_for_task(launch_input.task_id, root_node_key, 1),
        task_root=launch_input.task_root,
        workspace=launch_input.workspace,
        assignment=launch_input.assignment,
        workflow_revision=workflow_revision,
        initial_team=initial_team,
        compiled_plan=legacy_plan,
        max_child_assignments_per_assignment=(launch_input.max_child_assignments_per_assignment),
        max_retries_per_assignment=launch_input.max_retries_per_assignment,
        max_wave_members=launch_input.max_wave_members,
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
            "workflow_key": workflow_revision.workflow_id,
            "workflow_revision_no": workflow_revision.revision_no,
            "manifest_ref": f".banksia/{launch_input.task_id}/manifest.md",
        },
    )
    return StagedRuntimeLaunch(
        bootstrap=bootstrap,
        support_projection_signals=build_launch_support_projection_signals(bootstrap_input),
    )


__all__ = ["StagedRuntimeLaunch", "launch_task_runtime"]

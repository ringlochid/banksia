from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.runtime import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
    RuntimeLaunchInput,
)
from oh_my_subagents.runtime.contracts import TaskEventSource, TaskEventType
from oh_my_subagents.runtime.ids import assignment_id_for_task, attempt_id_for_task
from oh_my_subagents.runtime.launch.bootstrap import build_launch_support_projection_signals
from oh_my_subagents.runtime.launch.persistence.runtime import (
    persist_bootstrap_runtime_from_precomputed,
)
from oh_my_subagents.runtime.projection.signals import SupportProjectionSignal
from oh_my_subagents.runtime.task_events import append_task_event
from oh_my_subagents.runtime.team import plan_initial_task_team


@dataclass(frozen=True, slots=True)
class StagedRuntimeLaunch:
    """Controller rows and exact support hints staged by one Task launch."""

    bootstrap: RuntimeBootstrapResult
    support_projection_signals: tuple[SupportProjectionSignal, ...]


async def launch_task_runtime(
    session: AsyncSession,
    launch_input: RuntimeLaunchInput,
) -> StagedRuntimeLaunch:
    """Stage Task, Team, root Assignment/Attempt, and durable start-source truth."""

    workflow_revision = launch_input.workflow_revision
    initial_team = plan_initial_task_team(workflow_revision, launch_input.task_id)
    root_member_id = initial_team.root_member_id
    bootstrap_input = RuntimeBootstrapInput(
        task_id=launch_input.task_id,
        attempt_id=attempt_id_for_task(launch_input.task_id, root_member_id, 1),
        assignment_id=assignment_id_for_task(launch_input.task_id, root_member_id, 1),
        task_root=launch_input.task_root,
        workspace=launch_input.workspace,
        assignment=launch_input.assignment,
        workflow_revision=workflow_revision,
        initial_team=initial_team,
        max_child_assignments_per_assignment=launch_input.max_child_assignments_per_assignment,
        max_retries_per_assignment=launch_input.max_retries_per_assignment,
        max_wave_members=launch_input.max_wave_members,
    )
    bootstrap = await persist_bootstrap_runtime_from_precomputed(
        session,
        bootstrap_input,
        should_commit=False,
    )
    await append_task_event(
        session,
        task_id=launch_input.task_id,
        event_type=TaskEventType.TASK_STARTED,
        event_source=TaskEventSource.CONTROLLER,
        team_revision_id=initial_team.team_revision_id,
        member_id=root_member_id,
        payload={
            "workflow_key": workflow_revision.workflow_id,
            "workflow_revision_no": workflow_revision.revision_no,
            "manifest_ref": f".oms/{launch_input.task_id}/manifest.md",
        },
    )
    return StagedRuntimeLaunch(
        bootstrap=bootstrap,
        support_projection_signals=build_launch_support_projection_signals(bootstrap_input),
    )


__all__ = ["StagedRuntimeLaunch", "launch_task_runtime"]

from __future__ import annotations

from pathlib import Path

from banksia.persistence.models import AssignmentModel, FlowNodeModel, TaskModel
from banksia.runtime import RuntimeLaunchInput
from banksia.runtime.contracts import AssignmentBody
from banksia.runtime.launch.service import launch_task_runtime
from banksia.workflows.catalog import read_current_published_workflow
from sqlalchemy import select
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_runtime_launch_consumes_one_real_published_workflow_revision(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            workflow_revision = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            staged = await launch_task_runtime(
                session,
                RuntimeLaunchInput(
                    task_id="task.published-launch",
                    task_root=tmp_path / "task.published-launch",
                    workspace=tmp_path,
                    workflow_revision=workflow_revision,
                    assignment=AssignmentBody(
                        prompt="Launch exact reviewed-delivery truth.",
                    ),
                ),
            )
            await session.commit()

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.published-launch")
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == "task.published-launch")
            )
            nodes = tuple(
                (
                    await session.scalars(
                        select(FlowNodeModel)
                        .where(FlowNodeModel.task_id == "task.published-launch")
                        .order_by(FlowNodeModel.order_index)
                    )
                ).all()
            )

    assert task is not None
    assert task.workflow_key == "reviewed-delivery"
    assert task.workflow_revision_no == 1
    assert len(task.workflow_content_hash) == 64
    assert task.current_team_revision_id is not None
    assert task.max_child_assignments_per_assignment == 20
    assert task.max_retries_per_assignment == 1
    assert task.max_wave_members == 8
    assert assignment is not None
    assert assignment.member_id == "lead"
    assert assignment.child_assignment_limit == 20
    assert assignment.retry_limit == 1
    assert tuple(node.member_id for node in nodes) == (
        "lead",
        "delivery",
        "independent-review",
    )
    assert all(node.team_revision_id == task.current_team_revision_id for node in nodes)
    assert staged.bootstrap.assignment.prompt == "Launch exact reviewed-delivery truth."

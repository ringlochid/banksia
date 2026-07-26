from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from banksia.persistence.models import AssignmentModel, TaskModel, TeamRevisionMemberModel
from banksia.runtime import RuntimeLaunchInput
from banksia.runtime.contracts import AssignmentBody
from banksia.runtime.launch.service import launch_task_runtime
from banksia.workflows.catalog import read_current_published_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_runtime_launch_consumes_one_real_published_workflow_revision(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            workflow_revision = await read_current_published_workflow(
                session,
                workflow_id="reviewed-code-change",
            )
            staged = await launch_task_runtime(
                session,
                RuntimeLaunchInput(
                    task_id="task.published-launch",
                    task_root=tmp_path / "task.published-launch",
                    workspace=tmp_path,
                    workflow_revision=workflow_revision,
                    assignment=AssignmentBody(
                        prompt="Launch exact reviewed-code-change truth.",
                    ),
                ),
            )
            await session.commit()

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.published-launch")
            assert task is not None
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == "task.published-launch")
            )
            members = tuple(
                (
                    await session.scalars(
                        select(TeamRevisionMemberModel)
                        .where(
                            TeamRevisionMemberModel.task_id == "task.published-launch",
                            TeamRevisionMemberModel.team_revision_id
                            == task.current_team_revision_id,
                        )
                        .order_by(TeamRevisionMemberModel.preorder_index)
                    )
                ).all()
            )

    assert task.workflow_key == "reviewed-code-change"
    assert task.workflow_revision_no == 1
    assert len(task.workflow_content_hash) == 64
    assert task.current_team_revision_id is not None
    assert task.max_child_assignments_per_assignment == 20
    assert task.max_retries_per_assignment == 1
    assert task.max_wave_members == 8
    assert assignment is not None
    assert assignment.member_id == "change-lead"
    assert assignment.child_assignment_limit == 20
    assert assignment.retry_limit == 1
    assert tuple(member.member_id for member in members) == (
        "change-lead",
        "implementation-manager",
        "code-owner",
        "test-owner",
        "independent-reviewer",
    )
    assert all(member.team_revision_id == task.current_team_revision_id for member in members)
    assert staged.bootstrap.assignment.prompt == "Launch exact reviewed-code-change truth."

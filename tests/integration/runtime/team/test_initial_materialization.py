from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from oh_my_subagents.runtime.team import (
    InitialTaskTeam,
    TeamMaterializationError,
    materialize_initial_task_team,
)
from oh_my_subagents.workflows.contracts import PublishedWorkflowRevision
from tests.helpers.generic_workflow import (
    GENERIC_BRANCHING_WORKFLOW_ID,
    publish_generic_branching_workflow,
)
from tests.helpers.workflow_runtime import initialized_workflow_database

_EXPECTED_BRANCHING_MEMBER_IDS = (
    "coordinator",
    "branch-coordinator",
    "first-contributor",
    "second-contributor",
    "peer-reviewer",
)
_EXPECTED_BRANCHING_PARENT_IDS = (
    None,
    "coordinator",
    "branch-coordinator",
    "branch-coordinator",
    "coordinator",
)
_EXPECTED_BRANCHING_PREORDER = (0, 1, 2, 3, 4)
_EXPECTED_BRANCHING_SIBLING_ORDER = (0, 0, 0, 1, 1)


async def test_initial_team_materialization_pins_one_exact_complete_ordered_snapshot(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        published = await publish_generic_branching_workflow(session_factory)
        async with session_factory() as session:
            _stage_task(session, published=published, tmp_path=tmp_path)
            await session.flush()

            result = await materialize_initial_task_team(
                session,
                published,
                task_id="task.materialized",
            )
            await session.commit()

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.materialized")
            members = tuple(
                (
                    await session.scalars(
                        select(MemberModel)
                        .where(MemberModel.task_id == "task.materialized")
                        .order_by(MemberModel.member_id)
                    )
                ).all()
            )
            configurations = tuple(
                (
                    await session.scalars(
                        select(MemberConfigurationModel)
                        .where(MemberConfigurationModel.task_id == "task.materialized")
                        .order_by(MemberConfigurationModel.member_id)
                    )
                ).all()
            )
            branch_bases = tuple(
                (
                    await session.scalars(
                        select(MemberBranchBasisModel)
                        .where(MemberBranchBasisModel.task_id == "task.materialized")
                        .order_by(MemberBranchBasisModel.member_id)
                    )
                ).all()
            )
            selection = tuple(
                (
                    await session.scalars(
                        select(TeamRevisionMemberModel)
                        .where(TeamRevisionMemberModel.task_id == "task.materialized")
                        .order_by(TeamRevisionMemberModel.preorder_index)
                    )
                ).all()
            )
            team_revision = await session.get(
                TeamRevisionModel,
                result.team_revision_id,
            )

    _assert_materialized_team(
        task=task,
        team_revision=team_revision,
        members=members,
        configurations=configurations,
        branch_bases=branch_bases,
        selection=selection,
        published=published,
        result=result,
    )


def test_initial_team_materializer_has_no_caller_supplied_plan_parameter() -> None:
    assert "planned_team" not in inspect.signature(materialize_initial_task_team).parameters


async def test_initial_team_materialization_rejects_wrong_workflow_before_writes(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        published = await publish_generic_branching_workflow(session_factory)
        async with session_factory() as session:
            _stage_task(session, published=published, tmp_path=tmp_path, task_id="task.wrong-pin")
            await session.commit()

        wrong_revision = published.model_copy(
            update={"revision_no": published.revision_no + 1, "content_hash": "f" * 64}
        )
        async with session_factory() as session:
            with pytest.raises(TeamMaterializationError, match="Workflow pin"):
                await materialize_initial_task_team(
                    session,
                    wrong_revision,
                    task_id="task.wrong-pin",
                )
            await session.rollback()

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.wrong-pin")
            persisted_team_count = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionModel)
                .where(TeamRevisionModel.task_id == "task.wrong-pin")
            )

    assert task is not None and task.current_team_revision_id is None
    assert persisted_team_count == 0


async def test_initial_team_materialization_failure_rolls_back_claim_and_partial_rows(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        published = await publish_generic_branching_workflow(session_factory)
        async with session_factory() as session:
            _stage_task(session, published=published, tmp_path=tmp_path, task_id="task.rollback")
            session.add(MemberModel(task_id="task.rollback", member_id=published.workflow.lead.id))
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                await materialize_initial_task_team(
                    session,
                    published,
                    task_id="task.rollback",
                )
            await session.rollback()

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.rollback")
            persisted_team_count = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionModel)
                .where(TeamRevisionModel.task_id == "task.rollback")
            )
            configuration_count = await session.scalar(
                select(func.count())
                .select_from(MemberConfigurationModel)
                .where(MemberConfigurationModel.task_id == "task.rollback")
            )

    assert task is not None and task.current_team_revision_id is None
    assert persisted_team_count == 0
    assert configuration_count == 0


async def test_concurrent_initial_team_materializers_commit_one_winner(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        published = await publish_generic_branching_workflow(session_factory)
        async with session_factory() as session:
            _stage_task(session, published=published, tmp_path=tmp_path, task_id="task.race")
            await session.commit()

        async def materialize() -> str:
            async with session_factory() as session:
                try:
                    await materialize_initial_task_team(
                        session,
                        published,
                        task_id="task.race",
                    )
                    await session.commit()
                except TeamMaterializationError:
                    await session.rollback()
                    return "lost"
                return "won"

        outcomes = await asyncio.gather(materialize(), materialize())

        async with session_factory() as session:
            task = await session.get(TaskModel, "task.race")
            persisted_team_count = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionModel)
                .where(TeamRevisionModel.task_id == "task.race")
            )

    assert sorted(outcomes) == ["lost", "won"]
    assert task is not None and task.current_team_revision_id is not None
    assert persisted_team_count == 1


def _stage_task(
    session: AsyncSession,
    *,
    published: PublishedWorkflowRevision,
    tmp_path: Path,
    task_id: str = "task.materialized",
) -> None:
    session.add(
        TaskModel(
            task_id=task_id,
            workflow_key=published.workflow_id,
            workflow_revision_no=published.revision_no,
            workflow_content_hash=published.content_hash,
            current_team_revision_id=None,
            max_child_assignments_per_assignment=20,
            max_retries_per_assignment=1,
            max_wave_members=8,
            task_root_path=str(tmp_path / task_id),
        )
    )


def _assert_materialized_team(
    *,
    task: TaskModel | None,
    team_revision: TeamRevisionModel | None,
    members: tuple[MemberModel, ...],
    configurations: tuple[MemberConfigurationModel, ...],
    branch_bases: tuple[MemberBranchBasisModel, ...],
    selection: tuple[TeamRevisionMemberModel, ...],
    published: PublishedWorkflowRevision,
    result: InitialTaskTeam,
) -> None:
    assert task is not None
    assert task.workflow_key == published.workflow_id
    assert task.workflow_revision_no == published.revision_no
    assert task.workflow_content_hash == published.content_hash
    assert task.current_team_revision_id == result.team_revision_id
    assert task.max_child_assignments_per_assignment == 20
    assert task.max_retries_per_assignment == 1
    assert task.max_wave_members == 8

    assert team_revision is not None
    assert team_revision.revision_no == 1
    assert team_revision.predecessor_team_revision_id is None
    assert team_revision.root_member_id == published.workflow.lead.id
    assert team_revision.workflow_key == published.workflow_id
    assert team_revision.workflow_revision_no == published.revision_no
    assert team_revision.workflow_content_hash == published.content_hash

    assert published.workflow_id == GENERIC_BRANCHING_WORKFLOW_ID
    assert published.workflow.id == GENERIC_BRANCHING_WORKFLOW_ID
    assert published.workflow.lead.id == _EXPECTED_BRANCHING_MEMBER_IDS[0]
    direct_children = published.workflow.lead.children
    assert published.workflow.note
    assert direct_children is not None and len(direct_children) == 2
    nested_children = direct_children[0].children
    assert nested_children is not None and len(nested_children) == 2
    assert direct_children[1].children is None
    authored_members = (
        published.workflow.lead,
        direct_children[0],
        *nested_children,
        direct_children[1],
    )
    assert tuple(member.id for member in authored_members) == _EXPECTED_BRANCHING_MEMBER_IDS
    assert all(member.provider is None for member in authored_members)
    assert all(member.capabilities is None for member in authored_members)

    assert result.root_member_id == _EXPECTED_BRANCHING_MEMBER_IDS[0]
    assert tuple(row.member_id for row in result.members) == _EXPECTED_BRANCHING_MEMBER_IDS
    assert tuple(row.parent_member_id for row in result.members) == _EXPECTED_BRANCHING_PARENT_IDS
    assert tuple(row.preorder_index for row in result.members) == _EXPECTED_BRANCHING_PREORDER
    assert tuple(row.sibling_order for row in result.members) == _EXPECTED_BRANCHING_SIBLING_ORDER

    assert tuple(row.member_id for row in selection) == _EXPECTED_BRANCHING_MEMBER_IDS
    assert tuple(row.parent_member_id for row in selection) == _EXPECTED_BRANCHING_PARENT_IDS
    assert tuple(row.preorder_index for row in selection) == _EXPECTED_BRANCHING_PREORDER
    assert tuple(row.sibling_order for row in selection) == _EXPECTED_BRANCHING_SIBLING_ORDER

    expected_sorted_ids = tuple(sorted(_EXPECTED_BRANCHING_MEMBER_IDS))
    assert tuple(row.member_id for row in members) == expected_sorted_ids
    assert tuple(row.member_id for row in configurations) == expected_sorted_ids
    assert tuple(row.member_id for row in branch_bases) == expected_sorted_ids
    assert all(row.predecessor_member_configuration_id is None for row in configurations)
    assert all(row.requested_capabilities_json is None for row in configurations)
    assert all(row.requested_provider_json is None for row in configurations)
    assert {row.member_id: row.member_configuration_id for row in selection} == {
        row.member_id: row.member_configuration_id for row in configurations
    }
    assert {row.member_id: row.member_branch_basis_id for row in selection} == {
        row.member_id: row.member_branch_basis_id for row in branch_bases
    }

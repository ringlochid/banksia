from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts.team_read import (
    MemberAvailability,
    MemberParticipation,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.team.reads import read_direct_team_members
from tests.helpers.executor_harness import AsyncSessionFactory, seeded_async_executor
from tests.helpers.lineage_seed import FIXTURE_TIMESTAMP, RuntimeIds
from tests.helpers.postgres_runtime_race import postgres_runtime_harness
from tests.helpers.team_persistence_seed import member_branch_basis_id

type TeamSessionFactory = AsyncSessionFactory | async_sessionmaker[AsyncSession]


async def test_direct_team_read_batches_width_thirty_two_with_distinct_state(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="direct-team-batch") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        await _assert_wide_direct_team_read(
            session_factory,
            ids,
            expected_dialect="sqlite",
        )


async def test_postgresql_direct_team_read_batches_width_thirty_two() -> None:
    async with postgres_runtime_harness(suffix="direct-team-batch") as harness:
        await _assert_wide_direct_team_read(
            harness.session_factory,
            harness.ids,
            expected_dialect="postgresql",
        )


async def test_direct_team_read_retains_missing_configuration_error(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="direct-team-missing") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        missing = TeamRevisionMemberModel(
            task_id=ids.task_id,
            team_revision_id=ids.team_revision_id,
            member_id="missing-child",
            parent_member_id=ids.root_member_id,
            member_configuration_id="member-configuration.missing",
            member_branch_basis_id="member-branch-basis.missing",
            preorder_index=2,
            sibling_order=1,
        )
        async with session_factory() as session:
            with pytest.raises(
                ValueError,
                match="Team Member 'missing-child' is missing its configuration",
            ):
                await read_direct_team_members(
                    session,
                    children=(missing,),
                    dependencies=_dispatch_dependencies(),
                )


async def _seed_wide_direct_team(
    session_factory: TeamSessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as session:
        child_checkpoint = await session.get(AttemptCheckpointModel, ids.child_checkpoint_id)
        child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
        child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        assert child_checkpoint is not None
        assert child_attempt is not None
        assert child_assignment is not None
        now = utc_now()
        child_checkpoint.outcome = "green"
        child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
        child_attempt.status = "completed"
        child_attempt.terminal_outcome = "green"
        child_attempt.closed_at = now
        child_assignment.terminal_outcome = "green"
        child_assignment.closed_at = now
        session.add(
            AcceptedBoundaryModel(
                accepted_boundary_id=f"accepted-boundary.{ids.child_dispatch_id}",
                source_dispatch_id=ids.child_dispatch_id,
                task_id=ids.task_id,
                assignment_id=ids.child_assignment_id,
                attempt_id=ids.child_attempt_id,
                outcome="green",
                checkpoint_id=ids.child_checkpoint_id,
                successor_attempt_id=None,
                successor_dispatch_id=None,
                committed_at=now,
            )
        )
        root_basis_id = member_branch_basis_id(ids, ids.root_member_id)
        members: list[MemberModel] = []
        configurations: list[MemberConfigurationModel] = []
        branch_bases: list[MemberBranchBasisModel] = []
        selections: list[TeamRevisionMemberModel] = []
        for index in range(1, 32):
            member, configuration, branch_basis, selection = _child_selection_rows(
                ids=ids,
                index=index,
                root_basis_id=root_basis_id,
            )
            members.append(member)
            configurations.append(configuration)
            branch_bases.append(branch_basis)
            selections.append(selection)
        session.add_all(members)
        await session.flush()
        session.add_all(configurations)
        await session.flush()
        session.add_all(branch_bases)
        await session.flush()
        session.add_all(selections)
        await session.flush()
        session.add(
            AssignmentModel(
                assignment_id=f"assignment.{ids.suffix}.batch-01",
                task_id=ids.task_id,
                member_id="batch-child-01",
                assignment_key=f"assignment-key.{ids.suffix}.batch-01",
                parent_assignment_id=ids.root_assignment_id,
                prompt="Keep the first batch child busy.",
                current_attempt_id=None,
                work_plan_revision=0,
                child_assignment_limit=20,
                child_assignments_remaining=20,
                retry_limit=1,
                retries_remaining=1,
                created_by_dispatch_id=ids.current_dispatch_id,
                created_at=FIXTURE_TIMESTAMP,
                terminal_outcome=None,
                closed_at=None,
                superseded_at=None,
            )
        )
        await session.commit()


async def _assert_wide_direct_team_read(
    session_factory: TeamSessionFactory,
    ids: RuntimeIds,
    *,
    expected_dialect: str,
) -> None:
    await _seed_wide_direct_team(session_factory, ids)
    async with session_factory() as session:
        children = tuple(
            await session.scalars(
                select(TeamRevisionMemberModel)
                .where(
                    TeamRevisionMemberModel.task_id == ids.task_id,
                    TeamRevisionMemberModel.team_revision_id == ids.team_revision_id,
                    TeamRevisionMemberModel.parent_member_id == ids.root_member_id,
                )
                .order_by(TeamRevisionMemberModel.sibling_order)
            )
        )
        query_count = 0
        bind = session.get_bind()
        assert bind.dialect.name == expected_dialect

        def count_select(
            _connection: object,
            _cursor: object,
            statement: str,
            *_args: object,
        ) -> None:
            nonlocal query_count
            if statement.lstrip().upper().startswith("SELECT"):
                query_count += 1

        event.listen(bind, "before_cursor_execute", count_select)
        try:
            direct_team = await read_direct_team_members(
                session,
                children=children,
                dependencies=_dispatch_dependencies(),
            )
        finally:
            event.remove(bind, "before_cursor_execute", count_select)

    assert query_count == 3
    assert len(direct_team) == 32
    assert [member.id for member in direct_team] == [child.member_id for child in children]
    assert direct_team[0].participation is MemberParticipation.SATISFIED
    assert all(member.participation is MemberParticipation.REQUIRED for member in direct_team[1:])
    assert direct_team[1].availability is MemberAvailability.BUSY
    assert all(member.availability is MemberAvailability.AVAILABLE for member in direct_team[2:])
    assert direct_team[1].provider.model == "codex-batch-01"
    assert direct_team[2].provider.model == "codex-batch-02"
    assert direct_team[1].capabilities.command_run == "deny"
    assert direct_team[2].capabilities.human_request == ("input",)


def _child_selection_rows(
    *,
    ids: RuntimeIds,
    index: int,
    root_basis_id: str,
) -> tuple[
    MemberModel,
    MemberConfigurationModel,
    MemberBranchBasisModel,
    TeamRevisionMemberModel,
]:
    member_id = f"batch-child-{index:02d}"
    configuration_id = f"member-configuration.{ids.suffix}.{member_id}.1"
    branch_basis_id = f"member-branch-basis.{ids.suffix}.{member_id}.1"
    capability_request = (
        {"human_request": ["direction"]}
        if index % 3 == 1
        else {"human_request": ["input"], "command_run": "allow"}
        if index % 3 == 2
        else {"human_request": ["review"]}
    )
    return (
        MemberModel(
            task_id=ids.task_id,
            member_id=member_id,
            created_at=FIXTURE_TIMESTAMP,
        ),
        MemberConfigurationModel(
            member_configuration_id=configuration_id,
            task_id=ids.task_id,
            member_id=member_id,
            predecessor_member_configuration_id=None,
            title=f"Batch Child {index:02d}",
            description=f"Distinct batch child {index:02d}.",
            instruction=f"Use exact configuration {index:02d}.",
            requested_provider_json={
                "kind": "codex",
                "model": f"codex-batch-{index:02d}",
            },
            requested_capabilities_json=capability_request,
            basis_kind="workflow_revision",
            basis_id=f"workflow:{ids.suffix}",
            created_at=FIXTURE_TIMESTAMP,
        ),
        MemberBranchBasisModel(
            member_branch_basis_id=branch_basis_id,
            task_id=ids.task_id,
            member_id=member_id,
            member_configuration_id=configuration_id,
            parent_member_id=ids.root_member_id,
            parent_member_branch_basis_id=root_basis_id,
            created_at=FIXTURE_TIMESTAMP,
        ),
        TeamRevisionMemberModel(
            task_id=ids.task_id,
            team_revision_id=ids.team_revision_id,
            member_id=member_id,
            parent_member_id=ids.root_member_id,
            member_configuration_id=configuration_id,
            member_branch_basis_id=branch_basis_id,
            preorder_index=index + 1,
            sibling_order=index,
        ),
    )


def _dispatch_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )

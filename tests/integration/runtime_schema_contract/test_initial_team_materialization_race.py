from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from oh_my_subagents.persistence.models import (
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from oh_my_subagents.persistence.session import create_runtime_schema_tables
from oh_my_subagents.runtime.team import (
    InitialTaskTeam,
    TeamMaterializationError,
    materialize_initial_task_team,
)
from oh_my_subagents.workflows.contracts import PublishedWorkflowRevision
from tests.helpers.disposable_postgres import read_disposable_postgres_url
from tests.helpers.launch_foundation import (
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.postgres_runtime_race import (
    observe_update_order,
    wait_for_thread_event,
)

TASK_ID = "task.postgres-team-race"

type SessionFactory = async_sessionmaker[AsyncSession]
type MaterializationOutcome = InitialTaskTeam | BaseException


@dataclass(frozen=True, slots=True)
class _PersistedInitialTeam:
    task: TaskModel | None
    team_revisions: tuple[TeamRevisionModel, ...]
    members: tuple[MemberModel, ...]
    configurations: tuple[MemberConfigurationModel, ...]
    branch_bases: tuple[MemberBranchBasisModel, ...]
    selections: tuple[TeamRevisionMemberModel, ...]


@pytest.mark.asyncio
async def test_postgresql_initial_team_materialization_has_one_cas_winner() -> None:
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_initial_team_race_{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        execution_options={"schema_translate_map": {None: schema_name}},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    published = build_launch_foundation_workflow_revision()
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
        schema_created = True
        await _create_race_tables(engine, published)
        await _stage_unmaterialized_task(session_factory, published)

        outcomes = await _race_initial_team_materializers(
            engine,
            session_factory,
            published,
        )
        persisted = await _read_persisted_initial_team(session_factory)
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()

    winner = _assert_one_exact_materialization_loser(outcomes)
    _assert_complete_winning_graph(persisted, winner, published)


async def _create_race_tables(
    engine: AsyncEngine,
    published: PublishedWorkflowRevision,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(create_runtime_schema_tables)
        await connection.run_sync(
            lambda sync_connection: seed_launch_foundation_workflow(
                sync_connection,
                workflow_revision=published,
            )
        )


async def _stage_unmaterialized_task(
    session_factory: SessionFactory,
    published: PublishedWorkflowRevision,
) -> None:
    async with session_factory() as session:
        session.add(
            TaskModel(
                task_id=TASK_ID,
                workflow_key=published.workflow_id,
                workflow_revision_no=published.revision_no,
                workflow_content_hash=published.content_hash,
                current_team_revision_id=None,
                max_child_assignments_per_assignment=20,
                max_retries_per_assignment=1,
                max_wave_members=8,
                task_root_path=f"/tmp/{TASK_ID}",
            )
        )
        await session.commit()


async def _race_initial_team_materializers(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    published: PublishedWorkflowRevision,
) -> tuple[MaterializationOutcome, ...]:
    async with session_factory() as lock_session:
        locked_task = await lock_session.scalar(
            select(TaskModel).where(TaskModel.task_id == TASK_ID).with_for_update()
        )
        assert locked_task is not None

        with observe_update_order(engine, table_name="tasks") as task_updates:
            contenders = tuple(
                asyncio.create_task(_materialize_initial_team(session_factory, published))
                for _ in range(2)
            )
            try:
                await wait_for_thread_event(task_updates.first_update_started)
                await wait_for_thread_event(task_updates.second_update_started)
            except BaseException:
                await lock_session.rollback()
                for contender in contenders:
                    contender.cancel()
                await asyncio.gather(*contenders, return_exceptions=True)
                raise
            await lock_session.rollback()

        return tuple(await asyncio.gather(*contenders, return_exceptions=True))


async def _materialize_initial_team(
    session_factory: SessionFactory,
    published: PublishedWorkflowRevision,
) -> InitialTaskTeam:
    async with session_factory() as session:
        try:
            materialized = await materialize_initial_task_team(
                session,
                published,
                task_id=TASK_ID,
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return materialized


async def _read_persisted_initial_team(
    session_factory: SessionFactory,
) -> _PersistedInitialTeam:
    async with session_factory() as session:
        task = await session.get(TaskModel, TASK_ID)
        team_revisions = tuple(
            (
                await session.scalars(
                    select(TeamRevisionModel).where(TeamRevisionModel.task_id == TASK_ID)
                )
            ).all()
        )
        members = tuple(
            (
                await session.scalars(
                    select(MemberModel)
                    .where(MemberModel.task_id == TASK_ID)
                    .order_by(MemberModel.member_id)
                )
            ).all()
        )
        configurations = tuple(
            (
                await session.scalars(
                    select(MemberConfigurationModel)
                    .where(MemberConfigurationModel.task_id == TASK_ID)
                    .order_by(MemberConfigurationModel.member_id)
                )
            ).all()
        )
        branch_bases = tuple(
            (
                await session.scalars(
                    select(MemberBranchBasisModel)
                    .where(MemberBranchBasisModel.task_id == TASK_ID)
                    .order_by(MemberBranchBasisModel.member_id)
                )
            ).all()
        )
        selections = tuple(
            (
                await session.scalars(
                    select(TeamRevisionMemberModel)
                    .where(TeamRevisionMemberModel.task_id == TASK_ID)
                    .order_by(TeamRevisionMemberModel.preorder_index)
                )
            ).all()
        )
    return _PersistedInitialTeam(
        task=task,
        team_revisions=team_revisions,
        members=members,
        configurations=configurations,
        branch_bases=branch_bases,
        selections=selections,
    )


def _assert_one_exact_materialization_loser(
    outcomes: tuple[MaterializationOutcome, ...],
) -> InitialTaskTeam:
    winners = tuple(outcome for outcome in outcomes if isinstance(outcome, InitialTaskTeam))
    losers = tuple(outcome for outcome in outcomes if isinstance(outcome, TeamMaterializationError))

    assert len(winners) == 1
    assert len(losers) == 1
    assert len(outcomes) == len(winners) + len(losers)
    assert str(losers[0]) == f"Task {TASK_ID!r} already has a current TeamRevision"
    return winners[0]


def _assert_complete_winning_graph(
    persisted: _PersistedInitialTeam,
    winner: InitialTaskTeam,
    published: PublishedWorkflowRevision,
) -> None:
    assert persisted.task is not None
    assert persisted.task.current_team_revision_id == winner.team_revision_id
    assert len(persisted.team_revisions) == 1
    team_revision = persisted.team_revisions[0]
    assert (
        team_revision.team_revision_id,
        team_revision.task_id,
        team_revision.root_member_id,
        team_revision.workflow_key,
        team_revision.workflow_revision_no,
        team_revision.workflow_content_hash,
    ) == (
        winner.team_revision_id,
        TASK_ID,
        winner.root_member_id,
        published.workflow_id,
        published.revision_no,
        published.content_hash,
    )

    expected_members = tuple(sorted(member.member_id for member in winner.members))
    assert tuple(member.member_id for member in persisted.members) == expected_members
    assert tuple(
        (configuration.member_id, configuration.member_configuration_id)
        for configuration in persisted.configurations
    ) == tuple(
        sorted((member.member_id, member.member_configuration_id) for member in winner.members)
    )
    assert tuple(
        (
            branch.member_id,
            branch.member_configuration_id,
            branch.member_branch_basis_id,
            branch.parent_member_id,
            branch.parent_member_branch_basis_id,
        )
        for branch in persisted.branch_bases
    ) == tuple(
        sorted(
            (
                member.member_id,
                member.member_configuration_id,
                member.member_branch_basis_id,
                member.parent_member_id,
                member.parent_member_branch_basis_id,
            )
            for member in winner.members
        )
    )
    assert tuple(
        (
            selection.member_id,
            selection.parent_member_id,
            selection.member_configuration_id,
            selection.member_branch_basis_id,
            selection.preorder_index,
            selection.sibling_order,
        )
        for selection in persisted.selections
    ) == tuple(
        (
            member.member_id,
            member.parent_member_id,
            member.member_configuration_id,
            member.member_branch_basis_id,
            member.preorder_index,
            member.sibling_order,
        )
        for member in winner.members
    )


__all__ = []

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from banksia.persistence import RuntimeBase
from banksia.persistence.models import TaskModel, TeamRevisionModel
from banksia.persistence.session import create_runtime_schema_tables
from banksia.runtime.team import TeamMaterializationError, materialize_initial_task_team
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.launch_foundation import (
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine
from tests.helpers.team_persistence_seed import (
    member_configuration_id,
    team_revision_id,
)

NOW = datetime(2026, 7, 23, tzinfo=UTC)
Mutation = Callable[[Connection, RuntimeIds], None]


@pytest.mark.parametrize(
    ("case_name", "mutation"),
    (
        (
            "branch-basis-configuration",
            lambda connection, ids: _select_other_configuration(connection, ids),
        ),
        (
            "configuration-predecessor-member",
            lambda connection, ids: _insert_cross_member_predecessor(connection, ids),
        ),
        (
            "dispatch-team-selection",
            lambda connection, ids: _mismatch_dispatch_team_selection(connection, ids),
        ),
        (
            "task-current-team-workflow",
            lambda connection, ids: _point_task_at_other_workflow_team(connection, ids),
        ),
        ("task-workflow-hash", lambda connection, ids: _change_task_workflow_hash(connection, ids)),
        ("team-workflow-hash", lambda connection, ids: _change_team_workflow_hash(connection, ids)),
        (
            "human-capability-widening",
            lambda connection, ids: _widen_human_capability(connection, ids),
        ),
        (
            "command-capability-widening",
            lambda connection, ids: _widen_command_capability(connection, ids),
        ),
        ("sandbox-mode-widening", lambda connection, ids: _widen_sandbox_mode(connection, ids)),
        (
            "sandbox-network-widening",
            lambda connection, ids: _widen_sandbox_network(connection, ids),
        ),
    ),
)
def test_sqlite_rejects_cross_record_and_capability_widening(
    tmp_path: Path,
    case_name: str,
    mutation: Mutation,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name=f"relationship-{case_name}.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix=case_name)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                mutation(connection, ids)
    finally:
        engine.dispose()


def test_openclaw_capability_snapshot_keeps_nullable_managed_sandbox_shape(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="openclaw-capability.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix="openclaw")
        with engine.begin() as connection:
            _convert_current_dispatch_to_openclaw(connection, ids)
    finally:
        engine.dispose()


def test_sqlite_allows_only_one_open_assignment_per_task_member(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="open-assignment.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix="open-assignment")

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_open_assignment(
                    connection,
                    ids,
                    assignment_id="assignment.open-assignment.duplicate",
                )

        with engine.begin() as connection:
            _close_assignment(connection, assignment_id=ids.root_assignment_id)
            _insert_open_assignment(
                connection,
                ids,
                assignment_id="assignment.open-assignment.replacement",
            )

        with engine.connect() as connection:
            open_assignment_ids = tuple(
                connection.scalars(
                    select(RuntimeBase.metadata.tables["assignments"].c.assignment_id).where(
                        RuntimeBase.metadata.tables["assignments"].c.task_id == ids.task_id,
                        RuntimeBase.metadata.tables["assignments"].c.member_id
                        == ids.root_member_id,
                        RuntimeBase.metadata.tables["assignments"].c.closed_at.is_(None),
                    )
                )
            )
        assert open_assignment_ids == ("assignment.open-assignment.replacement",)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_rejects_cross_record_and_capability_widening() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_relationship_integrity_{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        execution_options={"schema_translate_map": {None: schema_name}},
    )
    schema_created = False
    cases: tuple[tuple[str, Mutation], ...] = (
        ("branch", _select_other_configuration),
        ("predecessor", _insert_cross_member_predecessor),
        ("dispatch-selection", _mismatch_dispatch_team_selection),
        ("task-team", _point_task_at_other_workflow_team),
        ("task-hash", _change_task_workflow_hash),
        ("team-hash", _change_team_workflow_hash),
        ("human", _widen_human_capability),
        ("command", _widen_command_capability),
        ("sandbox", _widen_sandbox_mode),
        ("network", _widen_sandbox_network),
    )
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
            schema_created = True
            await connection.run_sync(create_runtime_schema_tables)
            await connection.run_sync(seed_catalog)
            scopes = {
                name: await connection.run_sync(
                    partial(seed_runtime_scope, suffix=f"postgres-{name}")
                )
                for name, _mutation in cases
            }
            openclaw_ids = await connection.run_sync(
                lambda sync_connection: seed_runtime_scope(
                    sync_connection,
                    suffix="postgres-openclaw",
                )
            )

        for name, mutation in cases:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.run_sync(
                        partial(_apply_mutation, mutation=mutation, ids=scopes[name])
                    )

        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: _convert_current_dispatch_to_openclaw(
                    sync_connection,
                    openclaw_ids,
                )
            )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_allows_only_one_open_assignment_per_task_member() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_open_assignment_{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        execution_options={"schema_translate_map": {None: schema_name}},
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
            schema_created = True
            await connection.run_sync(create_runtime_schema_tables)
            await connection.run_sync(seed_catalog)
            ids = await connection.run_sync(
                partial(seed_runtime_scope, suffix="postgres-open-assignment")
            )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: _insert_open_assignment(
                        sync_connection,
                        ids,
                        assignment_id="assignment.postgres-open-assignment.duplicate",
                    )
                )

        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: _replace_open_assignment(
                    sync_connection,
                    ids,
                    assignment_id="assignment.postgres-open-assignment.replacement",
                )
            )

        async with engine.connect() as connection:
            open_assignment_ids = tuple(
                (
                    await connection.scalars(
                        select(RuntimeBase.metadata.tables["assignments"].c.assignment_id).where(
                            RuntimeBase.metadata.tables["assignments"].c.task_id == ids.task_id,
                            RuntimeBase.metadata.tables["assignments"].c.member_id
                            == ids.root_member_id,
                            RuntimeBase.metadata.tables["assignments"].c.closed_at.is_(None),
                        )
                    )
                ).all()
            )
        assert open_assignment_ids == ("assignment.postgres-open-assignment.replacement",)
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_initial_team_materialization_has_one_cas_winner() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_team_materialization_race_{uuid4().hex}"
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
            await connection.run_sync(create_runtime_schema_tables)
            await connection.run_sync(
                lambda sync_connection: seed_launch_foundation_workflow(
                    sync_connection,
                    workflow_revision=published,
                )
            )
        async with session_factory() as session:
            session.add(
                TaskModel(
                    task_id="task.postgres-team-race",
                    workflow_key=published.workflow_id,
                    workflow_revision_no=published.revision_no,
                    workflow_content_hash=published.content_hash,
                    current_team_revision_id=None,
                    max_child_assignments_per_assignment=20,
                    max_retries_per_assignment=1,
                    max_wave_members=8,
                    task_root_path="/tmp/task.postgres-team-race",
                )
            )
            await session.commit()

        async def materialize() -> str:
            async with session_factory() as session:
                try:
                    await materialize_initial_task_team(
                        session,
                        published,
                        task_id="task.postgres-team-race",
                    )
                    await session.commit()
                except TeamMaterializationError:
                    await session.rollback()
                    return "lost"
                return "won"

        outcomes = await asyncio.gather(materialize(), materialize())
        async with session_factory() as session:
            task = await session.get(TaskModel, "task.postgres-team-race")
            team_count = await session.scalar(
                select(func.count())
                .select_from(TeamRevisionModel)
                .where(TeamRevisionModel.task_id == "task.postgres-team-race")
            )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()

    assert sorted(outcomes) == ["lost", "won"]
    assert task is not None and task.current_team_revision_id is not None
    assert team_count == 1


def _insert_configuration(
    connection: Connection,
    ids: RuntimeIds,
    *,
    configuration_id: str,
    member_id: str,
    predecessor_id: str,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["member_configurations"].insert(),
        {
            "member_configuration_id": configuration_id,
            "task_id": ids.task_id,
            "member_id": member_id,
            "predecessor_member_configuration_id": predecessor_id,
            "title": "Replacement",
            "description": None,
            "instruction": None,
            "requested_provider_json": None,
            "requested_capabilities_json": None,
            "basis_kind": "test",
            "basis_id": f"basis.{ids.suffix}.{configuration_id}",
            "created_at": NOW,
        },
    )


def _apply_mutation(
    connection: Connection,
    *,
    mutation: Mutation,
    ids: RuntimeIds,
) -> None:
    mutation(connection, ids)


def _insert_open_assignment(
    connection: Connection,
    ids: RuntimeIds,
    *,
    assignment_id: str,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["assignments"].insert(),
        {
            "assignment_id": assignment_id,
            "task_id": ids.task_id,
            "member_id": ids.root_member_id,
            "parent_assignment_id": None,
            "prompt": "Continue the root assignment.",
            "current_attempt_id": None,
            "work_plan_revision": 0,
            "child_assignment_limit": 20,
            "child_assignments_remaining": 20,
            "retry_limit": 1,
            "retries_remaining": 1,
            "created_by_dispatch_id": None,
            "created_at": NOW,
            "terminal_outcome": None,
            "closed_at": None,
        },
    )


def _close_assignment(connection: Connection, *, assignment_id: str) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["assignments"]
        .update()
        .where(RuntimeBase.metadata.tables["assignments"].c.assignment_id == assignment_id)
        .values(terminal_outcome="green", closed_at=NOW)
    )


def _replace_open_assignment(
    connection: Connection,
    ids: RuntimeIds,
    *,
    assignment_id: str,
) -> None:
    _close_assignment(connection, assignment_id=ids.root_assignment_id)
    _insert_open_assignment(connection, ids, assignment_id=assignment_id)


def _select_other_configuration(connection: Connection, ids: RuntimeIds) -> None:
    replacement_id = f"member-configuration.{ids.suffix}.root.2"
    _insert_configuration(
        connection,
        ids,
        configuration_id=replacement_id,
        member_id="root",
        predecessor_id=member_configuration_id(ids, "root"),
    )
    selections = RuntimeBase.metadata.tables["team_revision_members"]
    connection.execute(
        selections.update()
        .where(
            selections.c.task_id == ids.task_id,
            selections.c.member_id == "root",
        )
        .values(member_configuration_id=replacement_id)
    )


def _insert_cross_member_predecessor(connection: Connection, ids: RuntimeIds) -> None:
    _insert_configuration(
        connection,
        ids,
        configuration_id=f"member-configuration.{ids.suffix}.root.cross-member",
        member_id="root",
        predecessor_id=member_configuration_id(ids, "child"),
    )


def _mismatch_dispatch_team_selection(connection: Connection, ids: RuntimeIds) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    connection.execute(
        dispatches.update()
        .where(dispatches.c.dispatch_id == ids.current_dispatch_id)
        .values(member_configuration_id=member_configuration_id(ids, "child"))
    )


def _point_task_at_other_workflow_team(connection: Connection, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    other_key = f"workflow.other.{ids.suffix}"
    other_hash = "f" * 64
    connection.execute(
        tables["workflow_definitions"].insert(),
        {
            "workflow_key": other_key,
            "current_revision_no": None,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    connection.execute(
        tables["workflow_revisions"].insert(),
        {
            "workflow_revision_id": f"workflow-revision.other.{ids.suffix}.1",
            "workflow_key": other_key,
            "revision_no": 1,
            "content_hash": other_hash,
            "content_json": {},
            "provenance": "user",
            "source_path": None,
            "created_at": NOW,
        },
    )
    other_team_id = f"team-revision.{ids.suffix}.other-workflow"
    connection.execute(
        tables["team_revisions"].insert(),
        {
            "team_revision_id": other_team_id,
            "task_id": ids.task_id,
            "revision_no": 2,
            "predecessor_team_revision_id": team_revision_id(ids),
            "root_member_id": "root",
            "workflow_key": other_key,
            "workflow_revision_no": 1,
            "workflow_content_hash": other_hash,
            "provenance_json": {"kind": "test"},
            "created_at": NOW,
        },
    )
    source_selections = (
        connection.execute(
            select(tables["team_revision_members"]).where(
                tables["team_revision_members"].c.team_revision_id == team_revision_id(ids)
            )
        )
        .mappings()
        .all()
    )
    for selection in source_selections:
        connection.execute(
            tables["team_revision_members"].insert(),
            {
                "task_id": ids.task_id,
                "team_revision_id": other_team_id,
                "member_id": selection["member_id"],
                "parent_member_id": selection["parent_member_id"],
                "member_configuration_id": selection["member_configuration_id"],
                "member_branch_basis_id": selection["member_branch_basis_id"],
                "preorder_index": selection["preorder_index"],
                "sibling_order": selection["sibling_order"],
            },
        )
    connection.execute(
        tables["tasks"]
        .update()
        .where(tables["tasks"].c.task_id == ids.task_id)
        .values(current_team_revision_id=other_team_id)
    )


def _change_task_workflow_hash(connection: Connection, ids: RuntimeIds) -> None:
    tasks = RuntimeBase.metadata.tables["tasks"]
    connection.execute(
        tasks.update().where(tasks.c.task_id == ids.task_id).values(workflow_content_hash="e" * 64)
    )


def _change_team_workflow_hash(connection: Connection, ids: RuntimeIds) -> None:
    teams = RuntimeBase.metadata.tables["team_revisions"]
    connection.execute(
        teams.update()
        .where(teams.c.team_revision_id == team_revision_id(ids))
        .values(workflow_content_hash="e" * 64)
    )


def _widen_human_capability(connection: Connection, ids: RuntimeIds) -> None:
    capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
    connection.execute(
        capabilities.update()
        .where(capabilities.c.dispatch_id == ids.current_dispatch_id)
        .values(requested_human_input="deny")
    )


def _widen_command_capability(connection: Connection, ids: RuntimeIds) -> None:
    capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
    connection.execute(
        capabilities.update()
        .where(capabilities.c.dispatch_id == ids.current_dispatch_id)
        .values(requested_command_run="deny")
    )


def _widen_sandbox_mode(connection: Connection, ids: RuntimeIds) -> None:
    capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
    connection.execute(
        capabilities.update()
        .where(capabilities.c.dispatch_id == ids.current_dispatch_id)
        .values(
            requested_sandbox_mode="read_only",
            requested_sandbox_network="deny",
        )
    )


def _widen_sandbox_network(connection: Connection, ids: RuntimeIds) -> None:
    capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
    connection.execute(
        capabilities.update()
        .where(capabilities.c.dispatch_id == ids.current_dispatch_id)
        .values(
            requested_sandbox_mode="workspace_write",
            requested_sandbox_network="deny",
            effective_sandbox_mode="workspace_write",
            provider_native_access="restricted",
        )
    )


def _convert_current_dispatch_to_openclaw(connection: Connection, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["dispatch_turns"]
        .update()
        .where(tables["dispatch_turns"].c.dispatch_id == ids.current_dispatch_id)
        .values(
            requested_provider="openclaw",
            resolved_provider="openclaw",
            model_source=None,
            effort_source=None,
            gateway_profile="default",
            gateway_profile_source="provider_configuration",
        )
    )
    connection.execute(
        tables["dispatch_capability_sets"]
        .update()
        .where(tables["dispatch_capability_sets"].c.dispatch_id == ids.current_dispatch_id)
        .values(
            provider_kind="openclaw",
            requested_sandbox_mode=None,
            requested_sandbox_network=None,
            sandbox_request_source=None,
            effective_sandbox_mode=None,
            effective_sandbox_network=None,
            sandbox_mode_source=None,
            sandbox_network_source=None,
        )
    )


def _disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL") or os.environ.get("BANKSIA_DATABASE_URL")
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")

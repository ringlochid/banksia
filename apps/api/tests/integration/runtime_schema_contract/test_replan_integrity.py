from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from banksia.persistence import RuntimeBase
from banksia.persistence.session import create_runtime_schema_tables
from sqlalchemy import Connection, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine
from tests.helpers.team_persistence_seed import team_revision_id

NOW = datetime(2026, 7, 23, tzinfo=UTC)
Mutation = Callable[[Connection, RuntimeIds], None]
CASES: tuple[tuple[str, Mutation], ...] = (
    ("source-snapshot", lambda connection, ids: _insert_mismatched_source(connection, ids)),
    ("successor-lineage", lambda connection, ids: _insert_wrong_successor(connection, ids)),
    (
        "team-predecessor",
        lambda connection, ids: _insert_wrong_team_predecessor(connection, ids),
    ),
    ("flow-parent", lambda connection, ids: _insert_wrong_flow_parent(connection, ids)),
    ("team-wrong-root", lambda connection, ids: _insert_team_with_wrong_root(connection, ids)),
    (
        "team-missing-selected-root",
        lambda connection, ids: _insert_team_without_selected_root(connection, ids),
    ),
    (
        "team-multiple-roots",
        lambda connection, ids: _insert_team_with_multiple_roots(connection, ids),
    ),
)


@pytest.mark.parametrize(("case_name", "mutation"), CASES)
def test_sqlite_rejects_inexact_replan_relations(
    tmp_path: Path,
    case_name: str,
    mutation: Mutation,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name=f"replan-{case_name}.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix=f"replan-{case_name}")
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                mutation(connection, ids)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_rejects_inexact_replan_relations() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_replan_integrity_{uuid4().hex}"
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
            scopes = {
                name: await connection.run_sync(
                    partial(seed_runtime_scope, suffix=f"postgres-replan-{name}")
                )
                for name, _mutation in CASES
            }

        for name, mutation in CASES:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.run_sync(
                        partial(_apply_mutation, mutation=mutation, ids=scopes[name])
                    )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


def _apply_mutation(
    connection: Connection,
    *,
    mutation: Mutation,
    ids: RuntimeIds,
) -> None:
    mutation(connection, ids)


def _insert_mismatched_source(
    connection: Connection,
    ids: RuntimeIds,
) -> None:
    successor_team_id = f"team-revision.{ids.suffix}.replan-successor"
    successor_flow_id = f"flow-revision.{ids.suffix}.replan-successor"
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=successor_team_id,
        predecessor_team_revision_id=team_revision_id(ids),
    )
    _insert_flow_successor(
        connection,
        ids,
        successor_flow_id=successor_flow_id,
        parent_flow_revision_id=ids.flow_revision_id,
    )
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.mismatch",
            source_team_revision_id=successor_team_id,
            successor_team_revision_id=successor_team_id,
            source_flow_revision_id=successor_flow_id,
            successor_flow_revision_id=successor_flow_id,
        ),
    )


def _insert_wrong_team_predecessor(
    connection: Connection,
    ids: RuntimeIds,
) -> None:
    successor_team_id = f"team-revision.{ids.suffix}.wrong-predecessor"
    successor_flow_id = f"flow-revision.{ids.suffix}.valid-parent"
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=successor_team_id,
        predecessor_team_revision_id=None,
    )
    _insert_flow_successor(
        connection,
        ids,
        successor_flow_id=successor_flow_id,
        parent_flow_revision_id=ids.flow_revision_id,
    )
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.wrong-team-predecessor",
            source_team_revision_id=team_revision_id(ids),
            successor_team_revision_id=successor_team_id,
            source_flow_revision_id=ids.flow_revision_id,
            successor_flow_revision_id=successor_flow_id,
        ),
    )


def _insert_wrong_flow_parent(
    connection: Connection,
    ids: RuntimeIds,
) -> None:
    successor_team_id = f"team-revision.{ids.suffix}.valid-predecessor"
    successor_flow_id = f"flow-revision.{ids.suffix}.wrong-parent"
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=successor_team_id,
        predecessor_team_revision_id=team_revision_id(ids),
    )
    _insert_flow_successor(
        connection,
        ids,
        successor_flow_id=successor_flow_id,
        parent_flow_revision_id=None,
    )
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.wrong-flow-parent",
            source_team_revision_id=team_revision_id(ids),
            successor_team_revision_id=successor_team_id,
            source_flow_revision_id=ids.flow_revision_id,
            successor_flow_revision_id=successor_flow_id,
        ),
    )


def _insert_team_with_wrong_root(connection: Connection, ids: RuntimeIds) -> None:
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=f"team-revision.{ids.suffix}.wrong-root",
        predecessor_team_revision_id=team_revision_id(ids),
        root_member_id="child",
    )


def _insert_team_without_selected_root(connection: Connection, ids: RuntimeIds) -> None:
    missing_root_id = f"unselected-root-{ids.suffix}"
    connection.execute(
        RuntimeBase.metadata.tables["members"].insert(),
        {
            "task_id": ids.task_id,
            "member_id": missing_root_id,
            "created_at": NOW,
        },
    )
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=f"team-revision.{ids.suffix}.missing-selected-root",
        predecessor_team_revision_id=team_revision_id(ids),
        root_member_id=missing_root_id,
    )


def _insert_team_with_multiple_roots(connection: Connection, ids: RuntimeIds) -> None:
    _insert_team_successor(
        connection,
        ids,
        successor_team_id=f"team-revision.{ids.suffix}.multiple-roots",
        predecessor_team_revision_id=team_revision_id(ids),
        second_root_member_id="child",
    )


def _insert_team_successor(
    connection: Connection,
    ids: RuntimeIds,
    *,
    successor_team_id: str,
    predecessor_team_revision_id: str | None,
    root_member_id: str = "root",
    second_root_member_id: str | None = None,
) -> None:
    tables = RuntimeBase.metadata.tables
    source_team = (
        connection.execute(
            select(tables["team_revisions"]).where(
                tables["team_revisions"].c.team_revision_id == team_revision_id(ids)
            )
        )
        .mappings()
        .one()
    )
    connection.execute(
        tables["team_revisions"].insert(),
        {
            "team_revision_id": successor_team_id,
            "task_id": ids.task_id,
            "revision_no": 2,
            "predecessor_team_revision_id": predecessor_team_revision_id,
            "root_member_id": root_member_id,
            "workflow_key": source_team["workflow_key"],
            "workflow_revision_no": source_team["workflow_revision_no"],
            "workflow_content_hash": source_team["workflow_content_hash"],
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
        member_id = str(selection["member_id"])
        parent_member_id = selection["parent_member_id"]
        if member_id == second_root_member_id:
            parent_member_id = None
        connection.execute(
            tables["team_revision_members"].insert(),
            {
                "task_id": ids.task_id,
                "team_revision_id": successor_team_id,
                "member_id": member_id,
                "parent_member_id": parent_member_id,
                "member_configuration_id": selection["member_configuration_id"],
                "member_branch_basis_id": selection["member_branch_basis_id"],
                "preorder_index": selection["preorder_index"],
                "sibling_order": selection["sibling_order"],
            },
        )


def _insert_flow_successor(
    connection: Connection,
    ids: RuntimeIds,
    *,
    successor_flow_id: str,
    parent_flow_revision_id: str | None,
) -> None:
    tables = RuntimeBase.metadata.tables
    source_flow = (
        connection.execute(
            select(tables["flow_revisions"]).where(
                tables["flow_revisions"].c.flow_revision_id == ids.flow_revision_id
            )
        )
        .mappings()
        .one()
    )
    connection.execute(
        tables["flow_revisions"].insert(),
        {
            "flow_revision_id": successor_flow_id,
            "flow_id": ids.flow_id,
            "revision_no": 2,
            "parent_flow_revision_id": parent_flow_revision_id,
            "source_compiled_plan_id": source_flow["source_compiled_plan_id"],
            "cause": "add_child",
            "created_by_dispatch_id": ids.current_dispatch_id,
            "snapshot_json": {"kind": "test"},
            "adopted_at": NOW,
        },
    )


def _insert_wrong_successor(
    connection: Connection,
    ids: RuntimeIds,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.wrong-lineage",
            source_team_revision_id=team_revision_id(ids),
            successor_team_revision_id=team_revision_id(ids),
            source_flow_revision_id=ids.flow_revision_id,
            successor_flow_revision_id=ids.flow_revision_id,
            manifest_state="current",
            successor_state="opened",
            successor_dispatch_id=ids.current_dispatch_id,
            manifest_current_at=NOW,
            successor_opened_at=NOW,
        ),
    )


def _transition_values(
    ids: RuntimeIds,
    *,
    transition_id: str,
    source_team_revision_id: str,
    successor_team_revision_id: str,
    source_flow_revision_id: str,
    successor_flow_revision_id: str,
    manifest_state: str = "pending",
    successor_state: str = "blocked",
    successor_dispatch_id: str | None = None,
    manifest_current_at: datetime | None = None,
    successor_opened_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "replan_transition_id": transition_id,
        "task_id": ids.task_id,
        "flow_id": ids.flow_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": ids.current_dispatch_id,
        "operation": "add_child",
        "normalized_request_json": {},
        "committed_result_json": {},
        "source_team_revision_id": source_team_revision_id,
        "successor_team_revision_id": successor_team_revision_id,
        "source_flow_revision_id": source_flow_revision_id,
        "successor_flow_revision_id": successor_flow_revision_id,
        "manifest_state": manifest_state,
        "successor_state": successor_state,
        "successor_dispatch_id": successor_dispatch_id,
        "failure_code": None,
        "failure_detail": None,
        "committed_at": NOW,
        "manifest_current_at": manifest_current_at,
        "successor_opened_at": successor_opened_at,
        "updated_at": NOW,
    }


def _disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL") or os.environ.get("BANKSIA_DATABASE_URL")
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")

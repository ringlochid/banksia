from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from oh_my_subagents.persistence import RuntimeBase
from oh_my_subagents.persistence.session import create_runtime_schema_tables
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.disposable_postgres import read_disposable_postgres_url
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine

NOW = datetime(2026, 7, 23, tzinfo=UTC)
Mutation = Callable[[Connection, RuntimeIds], None]


def _successor_predecessor_mismatch(connection: Connection, ids: RuntimeIds) -> None:
    successor_id = _insert_successor_team(
        connection,
        ids,
        include_predecessor=False,
    )
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.predecessor-mismatch",
            source_team_revision_id=ids.team_revision_id,
            successor_team_revision_id=successor_id,
        ),
    )


def _successor_dispatch_lineage_mismatch(connection: Connection, ids: RuntimeIds) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["replan_transitions"].insert(),
        _transition_values(
            ids,
            transition_id=f"replan-transition.{ids.suffix}.lineage-mismatch",
            source_team_revision_id=ids.team_revision_id,
            successor_team_revision_id=ids.team_revision_id,
            manifest_state="current",
            successor_state="opened",
            successor_dispatch_id=ids.current_dispatch_id,
            manifest_current_at=NOW,
            successor_opened_at=NOW,
        ),
    )


def _team_root_not_selected(connection: Connection, ids: RuntimeIds) -> None:
    missing_root_id = f"unselected-root-{ids.suffix}"
    connection.execute(
        RuntimeBase.metadata.tables["members"].insert(),
        {"task_id": ids.task_id, "member_id": missing_root_id, "created_at": NOW},
    )
    _insert_successor_team(connection, ids, root_member_id=missing_root_id)


def _team_has_two_roots(connection: Connection, ids: RuntimeIds) -> None:
    _insert_successor_team(connection, ids, second_root_member_id=ids.child_member_id)


CASES: tuple[tuple[str, Mutation], ...] = (
    ("successor-predecessor", _successor_predecessor_mismatch),
    ("successor-lineage", _successor_dispatch_lineage_mismatch),
    ("team-root-selection", _team_root_not_selected),
    ("team-one-root", _team_has_two_roots),
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
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"oms_replan_integrity_{uuid4().hex}"
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


def _insert_successor_team(
    connection: Connection,
    ids: RuntimeIds,
    *,
    include_predecessor: bool = True,
    root_member_id: str | None = None,
    second_root_member_id: str | None = None,
) -> str:
    tables = RuntimeBase.metadata.tables
    successor_id = f"team-revision.{ids.suffix}.2"
    source_team = (
        connection.execute(
            select(tables["team_revisions"]).where(
                tables["team_revisions"].c.team_revision_id == ids.team_revision_id
            )
        )
        .mappings()
        .one()
    )
    connection.execute(
        tables["team_revisions"].insert(),
        {
            "team_revision_id": successor_id,
            "task_id": ids.task_id,
            "revision_no": 2,
            "predecessor_team_revision_id": (ids.team_revision_id if include_predecessor else None),
            "root_member_id": root_member_id or ids.root_member_id,
            "workflow_key": source_team["workflow_key"],
            "workflow_revision_no": source_team["workflow_revision_no"],
            "workflow_content_hash": source_team["workflow_content_hash"],
            "provenance_json": {"kind": "test"},
            "created_at": NOW,
        },
    )
    selections = (
        connection.execute(
            select(tables["team_revision_members"]).where(
                tables["team_revision_members"].c.team_revision_id == ids.team_revision_id
            )
        )
        .mappings()
        .all()
    )
    for selection in selections:
        member_id = str(selection["member_id"])
        parent_member_id = selection["parent_member_id"]
        if member_id == second_root_member_id:
            parent_member_id = None
        connection.execute(
            tables["team_revision_members"].insert(),
            {
                "task_id": ids.task_id,
                "team_revision_id": successor_id,
                "member_id": member_id,
                "parent_member_id": parent_member_id,
                "member_configuration_id": selection["member_configuration_id"],
                "member_branch_basis_id": selection["member_branch_basis_id"],
                "preorder_index": selection["preorder_index"],
                "sibling_order": selection["sibling_order"],
            },
        )
    return successor_id


def _transition_values(
    ids: RuntimeIds,
    *,
    transition_id: str,
    source_team_revision_id: str,
    successor_team_revision_id: str,
    manifest_state: str = "pending",
    successor_state: str = "blocked",
    successor_dispatch_id: str | None = None,
    manifest_current_at: datetime | None = None,
    successor_opened_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "replan_transition_id": transition_id,
        "task_id": ids.task_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": ids.current_dispatch_id,
        "operation": "add_child",
        "normalized_request_json": {},
        "committed_result_json": {},
        "source_team_revision_id": source_team_revision_id,
        "successor_team_revision_id": successor_team_revision_id,
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

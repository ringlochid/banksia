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

from banksia.persistence import RuntimeBase
from banksia.persistence.session import create_runtime_schema_tables
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.disposable_postgres import read_disposable_postgres_url
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine

NOW = datetime(2026, 7, 24, tzinfo=UTC)
Mutation = Callable[[Connection, dict[str, RuntimeIds]], None]


def _child_boundary_as_task_result(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    boundary_id = f"accepted-boundary.{ids.suffix}.child"
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=boundary_id,
        source_dispatch_id=ids.child_dispatch_id,
        assignment_id=ids.child_assignment_id,
        attempt_id=ids.child_attempt_id,
        checkpoint_id=ids.child_checkpoint_id,
        outcome="blocked",
    )
    _complete_task(
        connection,
        ids=ids,
        boundary_id=boundary_id,
        outcome="blocked",
    )


def _task_result_outcome_mismatch(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    boundary_id = f"accepted-boundary.{ids.suffix}.root"
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=boundary_id,
        source_dispatch_id=ids.root_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=ids.root_checkpoint_id,
        outcome="green",
    )
    _complete_task(
        connection,
        ids=ids,
        boundary_id=boundary_id,
        outcome="blocked",
    )


def _boundary_checkpoint_source_mismatch(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=f"accepted-boundary.{ids.suffix}.source-mismatch",
        source_dispatch_id=ids.current_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=ids.root_checkpoint_id,
        outcome="green",
    )


def _boundary_checkpoint_outcome_mismatch(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=f"accepted-boundary.{ids.suffix}.outcome-mismatch",
        source_dispatch_id=ids.root_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=ids.root_checkpoint_id,
        outcome="blocked",
    )


def _retry_successor_from_another_task(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    other = scopes["b"]
    checkpoint_id = _insert_retry_checkpoint(connection, ids=ids)
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=f"accepted-boundary.{ids.suffix}.cross-task-retry",
        source_dispatch_id=ids.current_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=checkpoint_id,
        outcome="retry",
        successor_attempt_id=other.root_attempt_id,
        successor_dispatch_id=other.root_dispatch_id,
    )


def _retry_successor_from_another_assignment(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    checkpoint_id = _insert_retry_checkpoint(connection, ids=ids)
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=f"accepted-boundary.{ids.suffix}.cross-assignment-retry",
        source_dispatch_id=ids.current_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=checkpoint_id,
        outcome="retry",
        successor_attempt_id=ids.child_attempt_id,
        successor_dispatch_id=ids.child_dispatch_id,
    )


def _retry_attempt_does_not_name_the_source_attempt(
    connection: Connection,
    scopes: dict[str, RuntimeIds],
) -> None:
    ids = scopes["a"]
    successor_attempt_id = f"attempt.{ids.suffix}.root.2"
    successor_dispatch_id = f"dispatch.{ids.suffix}.root.retry"
    _insert_non_retry_successor(
        connection,
        ids=ids,
        successor_attempt_id=successor_attempt_id,
        successor_dispatch_id=successor_dispatch_id,
    )
    checkpoint_id = _insert_retry_checkpoint(connection, ids=ids)
    _insert_boundary(
        connection,
        ids=ids,
        boundary_id=f"accepted-boundary.{ids.suffix}.missing-retry-owner",
        source_dispatch_id=ids.current_dispatch_id,
        assignment_id=ids.root_assignment_id,
        attempt_id=ids.root_attempt_id,
        checkpoint_id=checkpoint_id,
        outcome="retry",
        successor_attempt_id=successor_attempt_id,
        successor_dispatch_id=successor_dispatch_id,
    )


CASES: tuple[tuple[str, Mutation], ...] = (
    ("child-task-result", _child_boundary_as_task_result),
    ("result-outcome", _task_result_outcome_mismatch),
    ("checkpoint-source", _boundary_checkpoint_source_mismatch),
    ("checkpoint-outcome", _boundary_checkpoint_outcome_mismatch),
    ("retry-cross-task", _retry_successor_from_another_task),
    ("retry-cross-assignment", _retry_successor_from_another_assignment),
    ("retry-owner", _retry_attempt_does_not_name_the_source_attempt),
)


@pytest.mark.parametrize(("case_name", "mutation"), CASES)
def test_sqlite_rejects_inexact_controller_relationships(
    tmp_path: Path,
    case_name: str,
    mutation: Mutation,
) -> None:
    engine = create_runtime_schema_engine(
        tmp_path,
        name=f"exact-relationship-{case_name}.sqlite",
    )
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            scopes = {
                suffix: seed_runtime_scope(connection, suffix=f"{case_name}-{suffix}")
                for suffix in ("a", "b")
            }
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                mutation(connection, scopes)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_rejects_inexact_controller_relationships() -> None:
    database_url = read_disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_exact_relationships_{uuid4().hex}"
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

        for case_name, mutation in CASES:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.run_sync(
                        partial(
                            _seed_and_apply,
                            case_name=case_name,
                            mutation=mutation,
                        )
                    )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


def _seed_and_apply(
    connection: Connection,
    *,
    case_name: str,
    mutation: Mutation,
) -> None:
    scopes = {
        suffix: seed_runtime_scope(connection, suffix=f"postgres-{case_name}-{suffix}")
        for suffix in ("a", "b")
    }
    mutation(connection, scopes)


def _insert_boundary(
    connection: Connection,
    *,
    ids: RuntimeIds,
    boundary_id: str,
    source_dispatch_id: str,
    assignment_id: str,
    attempt_id: str,
    checkpoint_id: str,
    outcome: str,
    successor_attempt_id: str | None = None,
    successor_dispatch_id: str | None = None,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["accepted_boundaries"].insert(),
        {
            "accepted_boundary_id": boundary_id,
            "source_dispatch_id": source_dispatch_id,
            "task_id": ids.task_id,
            "assignment_id": assignment_id,
            "attempt_id": attempt_id,
            "outcome": outcome,
            "checkpoint_id": checkpoint_id,
            "successor_attempt_id": successor_attempt_id,
            "successor_dispatch_id": successor_dispatch_id,
            "committed_at": NOW,
        },
    )


def _complete_task(
    connection: Connection,
    *,
    ids: RuntimeIds,
    boundary_id: str,
    outcome: str,
) -> None:
    tasks = RuntimeBase.metadata.tables["tasks"]
    connection.execute(
        tasks.update()
        .where(tasks.c.task_id == ids.task_id)
        .values(
            status="completed",
            terminal_outcome=outcome,
            result_boundary_id=boundary_id,
            updated_at=NOW,
        )
    )


def _insert_retry_checkpoint(
    connection: Connection,
    *,
    ids: RuntimeIds,
) -> str:
    checkpoint_id = f"checkpoint.{ids.suffix}.retry"
    connection.execute(
        RuntimeBase.metadata.tables["attempt_checkpoints"].insert(),
        {
            "checkpoint_id": checkpoint_id,
            "task_id": ids.task_id,
            "assignment_id": ids.root_assignment_id,
            "attempt_id": ids.root_attempt_id,
            "authoring_dispatch_id": ids.current_dispatch_id,
            "outcome": "retry",
            "summary": "Retry the exact Assignment.",
            "details": None,
            "recorded_at": NOW,
        },
    )
    return checkpoint_id


def _insert_non_retry_successor(
    connection: Connection,
    *,
    ids: RuntimeIds,
    successor_attempt_id: str,
    successor_dispatch_id: str,
) -> None:
    tables = RuntimeBase.metadata.tables
    source_dispatch = (
        connection.execute(
            select(tables["dispatch_turns"]).where(
                tables["dispatch_turns"].c.dispatch_id == ids.current_dispatch_id
            )
        )
        .mappings()
        .one()
    )
    connection.execute(
        tables["attempts"].insert(),
        {
            "attempt_id": successor_attempt_id,
            "assignment_id": ids.root_assignment_id,
            "task_id": ids.task_id,
            "retry_of_attempt_id": None,
            "latest_checkpoint_id": None,
            "current_dispatch_id": successor_dispatch_id,
            "current_wait_id": None,
            "status": "running",
            "terminal_outcome": None,
            "opened_at": NOW,
            "closed_at": None,
        },
    )
    dispatch_values = dict(source_dispatch)
    dispatch_values.pop("active_status_marker")
    dispatch_values.update(
        dispatch_id=successor_dispatch_id,
        attempt_id=successor_attempt_id,
        task_start_source_task_id=None,
        predecessor_dispatch_id=None,
        opened_reason="semantic_retry",
    )
    connection.execute(tables["dispatch_turns"].insert(), dispatch_values)

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.schema_contract import verify_schema_contract
from sqlalchemy import Connection, inspect, make_url, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
REQUEST_ID = "human-request.current-dispatch-constraint"


@pytest.mark.parametrize("dispatch_status", ("open", "starting"))
def test_flow_current_dispatch_accepts_starting_and_open_dispatches(
    tmp_path: Path,
    dispatch_status: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            if dispatch_status == "starting":
                _set_current_dispatch_starting(connection, ids)

        with engine.connect() as connection:
            dispatch = connection.execute(
                select(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.status,
                    RuntimeBase.metadata.tables["dispatch_turns"].c.active_status_marker,
                ).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == ids.current_dispatch_id
                )
            ).one()
            flow_marker = connection.scalar(
                select(
                    RuntimeBase.metadata.tables["flows"].c.current_dispatch_presence_marker
                ).where(RuntimeBase.metadata.tables["flows"].c.flow_id == ids.flow_id)
            )

        assert dispatch.status == dispatch_status
        assert dispatch.active_status_marker == 1
        assert flow_marker == 1
    finally:
        engine.dispose()


def test_flow_current_dispatch_rejects_a_closed_dispatch(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _point_flow_at_closed_dispatch(connection, ids)
    finally:
        engine.dispose()


def test_closing_current_dispatch_requires_clearing_flow_authority(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _close_current_dispatch_for_wait(connection, ids)
    finally:
        engine.dispose()


def test_flow_current_dispatch_rejects_a_dispatch_from_another_owner(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            first = seed_runtime_scope(connection, suffix="first")
            second = seed_runtime_scope(connection, suffix="second")

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                flows = RuntimeBase.metadata.tables["flows"]
                connection.execute(
                    flows.update()
                    .where(flows.c.flow_id == first.flow_id)
                    .values(current_dispatch_id=second.current_dispatch_id)
                )
    finally:
        engine.dispose()


def test_flow_current_dispatch_rejects_a_non_none_wait_pointer(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                flows = RuntimeBase.metadata.tables["flows"]
                connection.execute(
                    flows.update()
                    .where(flows.c.flow_id == ids.flow_id)
                    .values(
                        waiting_cause="human_request",
                        waiting_source_id=REQUEST_ID,
                    )
                )
    finally:
        engine.dispose()


def test_flow_wait_rejects_current_dispatch_when_pointer_is_stale_none(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_human_request_and_wait(connection, ids)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("waiting_cause", "waiting_source_id"),
    (("human_request", REQUEST_ID), ("none", None)),
    ids=("pointer-matches-source", "stale-convenience-pointer"),
)
def test_flow_wait_is_valid_only_after_current_authority_is_cleared(
    tmp_path: Path,
    waiting_cause: str,
    waiting_source_id: str | None,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            _close_current_dispatch_for_wait(connection, ids)
            flows = RuntimeBase.metadata.tables["flows"]
            connection.execute(
                flows.update()
                .where(flows.c.flow_id == ids.flow_id)
                .values(
                    current_dispatch_id=None,
                    waiting_cause=waiting_cause,
                    waiting_source_id=waiting_source_id,
                )
            )
            _insert_human_request_and_wait(connection, ids)

        with engine.connect() as connection:
            flow = connection.execute(
                select(RuntimeBase.metadata.tables["flows"]).where(
                    RuntimeBase.metadata.tables["flows"].c.flow_id == ids.flow_id
                )
            ).one()
            wait = connection.execute(
                select(RuntimeBase.metadata.tables["flow_waits"]).where(
                    RuntimeBase.metadata.tables["flow_waits"].c.flow_id == ids.flow_id
                )
            ).one()

        assert flow.current_dispatch_id is None
        assert flow.current_dispatch_presence_marker == 0
        assert flow.waiting_cause == waiting_cause
        assert flow.waiting_source_id == waiting_source_id
        assert wait.required_current_dispatch_presence_marker == 0
        assert wait.human_request_id == REQUEST_ID
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_reflects_and_enforces_current_dispatch_constraints() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"autoclaw_currentness_{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        execution_options={"schema_translate_map": {None: schema_name}},
    )
    schema_created = False
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
            schema_created = True
            await connection.run_sync(RuntimeBase.metadata.create_all)
            await connection.run_sync(
                lambda sync_connection: verify_schema_contract(sync_connection, schema_name)
            )
            reflected_computed = await connection.run_sync(
                lambda sync_connection: _reflected_currentness_computed_columns(
                    sync_connection,
                    schema_name,
                )
            )
            ids = await connection.run_sync(_seed_postgres_runtime_scope)

        assert reflected_computed == {
            "dispatch_turns.active_status_marker": True,
            "flows.current_dispatch_presence_marker": True,
            "flow_waits.required_current_dispatch_presence_marker": True,
        }

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: _point_flow_at_closed_dispatch(
                        sync_connection,
                        ids,
                    )
                )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: _insert_human_request_and_wait(
                        sync_connection,
                        ids,
                    )
                )

        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: _persist_valid_wait(sync_connection, ids)
            )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


def _set_current_dispatch_starting(connection: Connection, ids: RuntimeIds) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    connection.execute(
        dispatches.update()
        .where(dispatches.c.dispatch_id == ids.current_dispatch_id)
        .values(
            status="starting",
            adapter_started_at=None,
            next_provider_start_at=NOW,
            provider_start_retry_kind="initial",
        )
    )


def _point_flow_at_closed_dispatch(connection: Connection, ids: RuntimeIds) -> None:
    flows = RuntimeBase.metadata.tables["flows"]
    connection.execute(
        flows.update()
        .where(flows.c.flow_id == ids.flow_id)
        .values(current_dispatch_id=ids.root_dispatch_id)
    )


def _close_current_dispatch_for_wait(connection: Connection, ids: RuntimeIds) -> None:
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    connection.execute(
        dispatches.update()
        .where(dispatches.c.dispatch_id == ids.current_dispatch_id)
        .values(
            status="closed",
            closed_at=NOW,
            closed_reason="human_request_wait",
        )
    )


def _insert_human_request_and_wait(connection: Connection, ids: RuntimeIds) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["human_requests"].insert(),
        _open_human_request(ids),
    )
    connection.execute(
        RuntimeBase.metadata.tables["flow_waits"].insert(),
        {
            "flow_id": ids.flow_id,
            "task_id": ids.task_id,
            "source_dispatch_id": ids.current_dispatch_id,
            "human_request_id": REQUEST_ID,
            "command_run_id": None,
            "created_at": NOW,
        },
    )


def _persist_valid_wait(connection: Connection, ids: RuntimeIds) -> None:
    _close_current_dispatch_for_wait(connection, ids)
    flows = RuntimeBase.metadata.tables["flows"]
    connection.execute(
        flows.update()
        .where(flows.c.flow_id == ids.flow_id)
        .values(
            current_dispatch_id=None,
            waiting_cause="human_request",
            waiting_source_id=REQUEST_ID,
        )
    )
    _insert_human_request_and_wait(connection, ids)


def _open_human_request(ids: RuntimeIds) -> dict[str, object]:
    return {
        "request_id": REQUEST_ID,
        "task_id": ids.task_id,
        "flow_id": ids.flow_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": ids.current_dispatch_id,
        "request_kind": "approval",
        "request_summary": "Approve the target transition.",
        "request_items_json": [{"id": "choice", "prompt": "Approve?"}],
        "context_refs_json": None,
        "suggested_human_instruction": None,
        "capability_basis_json": {"human_approval": "allow"},
        "due_at": None,
        "timeout_policy_json": None,
        "default_behavior_json": None,
        "status": "open",
        "resolution_kind": None,
        "item_responses_json": None,
        "resolution_policy_basis_json": None,
        "resolution_summary": None,
        "resolved_by_actor_ref": None,
        "resolved_by_surface": None,
        "successor_dispatch_id": None,
        "opened_at": NOW,
        "resolved_at": None,
    }


def _seed_postgres_runtime_scope(connection: Connection) -> RuntimeIds:
    seed_catalog(connection)
    return seed_runtime_scope(connection)


def _reflected_currentness_computed_columns(
    connection: Connection,
    schema_name: str,
) -> dict[str, bool | None]:
    reflected: dict[str, bool | None] = {}
    inspector = inspect(connection)
    for table_name, column_name in (
        ("dispatch_turns", "active_status_marker"),
        ("flows", "current_dispatch_presence_marker"),
        ("flow_waits", "required_current_dispatch_presence_marker"),
    ):
        columns = inspector.get_columns(table_name, schema=schema_name)
        column = next(item for item in columns if item["name"] == column_name)
        computed = column.get("computed")
        assert isinstance(computed, dict)
        reflected[f"{table_name}.{column_name}"] = computed.get("persisted")
    return reflected


def _disposable_postgres_url() -> URL | None:
    raw_url = os.environ.get("AUTOCLAW_TEST_POSTGRES_URL") or os.environ.get(
        "AUTOCLAW_DATABASE_URL"
    )
    if raw_url is None:
        return None
    database_url = make_url(raw_url)
    database_name = database_url.database or ""
    if database_url.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        return None
    return database_url.set(drivername="postgresql+asyncpg")

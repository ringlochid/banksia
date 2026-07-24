from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from banksia.persistence import RuntimeBase
from banksia.persistence.schema_contract import verify_schema_contract
from banksia.persistence.session import create_runtime_schema_tables
from banksia.providers import ManagedSandboxMode, NetworkAccess, ProviderKind
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.provider_resolution import (
    CodexProviderRoute,
    ManagedSandboxResolution,
    ProviderResolution,
    ProviderRouteValueSource,
    ProviderSelectionBasis,
    SandboxResolutionSource,
)
from banksia.runtime.dispatch.currentness import AttemptDispatchConflictError
from banksia.runtime.dispatch.opening import StartingDispatchBasis, stage_starting_dispatch
from banksia.runtime.dispatch.preparation import PreparedDispatchRequest
from sqlalchemy import Connection, make_url, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import RuntimeIds, seed_runtime_scope
from tests.helpers.sqlite_runtime import SyncSessionAdapter, create_runtime_schema_engine
from tests.helpers.team_persistence_seed import (
    member_branch_basis_id,
    member_configuration_id,
    team_revision_id,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
HUMAN_REQUEST_ID = "human-request.attempt-lane"
ATTEMPT_WAIT_ID = "attempt-wait.attempt-lane"

type SyncSessionFactory = sessionmaker[Session]


def test_attempts_in_one_flow_can_each_own_an_active_dispatch(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            child_current_id = f"{ids.child_dispatch_id}.continuation"
            connection.execute(
                RuntimeBase.metadata.tables["dispatch_turns"].insert(),
                _dispatch_row(
                    connection,
                    ids,
                    dispatch_id=child_current_id,
                    assignment_id=ids.child_assignment_id,
                    attempt_id=ids.child_attempt_id,
                    node_key="child",
                    predecessor_dispatch_id=ids.child_dispatch_id,
                    status="open",
                    opened_reason="child_return",
                ),
            )
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.child_attempt_id)
                .values(current_dispatch_id=child_current_id)
            )

        with engine.connect() as connection:
            lanes = dict(
                connection.execute(
                    select(
                        RuntimeBase.metadata.tables["attempts"].c.attempt_id,
                        RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id,
                    ).where(RuntimeBase.metadata.tables["attempts"].c.flow_id == ids.flow_id)
                )
                .tuples()
                .all()
            )

        assert lanes == {
            ids.root_attempt_id: ids.current_dispatch_id,
            ids.child_attempt_id: child_current_id,
        }
    finally:
        engine.dispose()


@pytest.mark.parametrize("duplicate_kind", ("first", "active"))
def test_one_attempt_rejects_duplicate_lineage_heads(
    tmp_path: Path,
    duplicate_kind: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name=f"{duplicate_kind}.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                is_first = duplicate_kind == "first"
                duplicate_id = f"dispatch.{duplicate_kind}.duplicate"
                connection.execute(
                    RuntimeBase.metadata.tables["dispatch_turns"].insert(),
                    _dispatch_row(
                        connection,
                        ids,
                        dispatch_id=duplicate_id,
                        assignment_id=ids.root_assignment_id,
                        attempt_id=ids.root_attempt_id,
                        node_key="root",
                        predecessor_dispatch_id=None if is_first else ids.current_dispatch_id,
                        status="closed" if is_first else "open",
                        opened_reason="boundary" if is_first else "child_return",
                    ),
                )
                if not is_first:
                    connection.execute(
                        RuntimeBase.metadata.tables["attempts"]
                        .update()
                        .where(
                            RuntimeBase.metadata.tables["attempts"].c.attempt_id
                            == ids.root_attempt_id
                        )
                        .values(current_dispatch_id=duplicate_id)
                    )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "invalid_transition",
    ("closed_pointer", "close_without_clear", "terminal_with_pointer"),
)
def test_attempt_current_pointer_rejects_invalid_lane_states(
    tmp_path: Path,
    invalid_transition: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name=f"{invalid_transition}.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                attempts = RuntimeBase.metadata.tables["attempts"]
                if invalid_transition == "closed_pointer":
                    _close_current_dispatch(connection, ids)
                    connection.execute(
                        attempts.update()
                        .where(attempts.c.attempt_id == ids.root_attempt_id)
                        .values(current_dispatch_id=ids.root_dispatch_id)
                    )
                elif invalid_transition == "close_without_clear":
                    _close_current_dispatch(connection, ids)
                else:
                    connection.execute(
                        attempts.update()
                        .where(attempts.c.attempt_id == ids.root_attempt_id)
                        .values(
                            status="completed",
                            terminal_outcome="green",
                            closed_at=NOW,
                        )
                    )
    finally:
        engine.dispose()


def test_dispatch_close_and_attempt_pointer_clear_commit_atomically(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            _close_current_dispatch(connection, ids)
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
                .values(current_dispatch_id=None)
            )

        with engine.connect() as connection:
            attempt_pointer = connection.scalar(
                select(RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id).where(
                    RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id
                )
            )
            dispatch_status = connection.scalar(
                select(RuntimeBase.metadata.tables["dispatch_turns"].c.status).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                    == ids.current_dispatch_id
                )
            )

        assert attempt_pointer is None
        assert dispatch_status == "closed"
    finally:
        engine.dispose()


def test_concurrent_starting_dispatch_writers_select_one_attempt_winner(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="starting-dispatch-race.sqlite")
    session_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection, suffix="starting-dispatch-race")
            _close_current_dispatch(connection, ids)
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
                .values(current_dispatch_id=None)
            )

        candidate_ids = (
            "dispatch.starting-race.candidate-a",
            "dispatch.starting-race.candidate-b",
        )
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(
                executor.submit(
                    _run_starting_dispatch_writer,
                    session_factory,
                    ids,
                    dispatch_id,
                    barrier,
                )
                for dispatch_id in candidate_ids
            )
            outcomes = tuple(future.result(timeout=10) for future in futures)

        with engine.connect() as connection:
            attempt = connection.execute(
                select(
                    RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id,
                    RuntimeBase.metadata.tables["attempts"].c.current_wait_id,
                ).where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
            ).one()
            staged_dispatches = connection.execute(
                select(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id,
                    RuntimeBase.metadata.tables["dispatch_turns"].c.predecessor_dispatch_id,
                ).where(
                    RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id.in_(candidate_ids)
                )
            ).all()
            staged_requests = connection.scalars(
                select(RuntimeBase.metadata.tables["dispatch_requests"].c.dispatch_id).where(
                    RuntimeBase.metadata.tables["dispatch_requests"].c.dispatch_id.in_(
                        candidate_ids
                    )
                )
            ).all()

        assert sorted(outcomes) == [False, True]
        assert len(staged_dispatches) == 1
        winner = staged_dispatches[0]
        assert attempt.current_dispatch_id == winner.dispatch_id
        assert attempt.current_wait_id is None
        assert winner.predecessor_dispatch_id == ids.current_dispatch_id
        assert staged_requests == [winner.dispatch_id]
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_wait", ("no_source", "dispatch_and_wait"))
def test_attempt_wait_rejects_incomplete_or_occupied_lane(
    tmp_path: Path,
    invalid_wait: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name=f"{invalid_wait}.sqlite")
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_human_request(connection, ids)
                connection.execute(
                    RuntimeBase.metadata.tables["attempt_waits"].insert(),
                    _attempt_wait_row(
                        ids,
                        human_request_id=(
                            None if invalid_wait == "no_source" else HUMAN_REQUEST_ID
                        ),
                    ),
                )
                if invalid_wait == "dispatch_and_wait":
                    connection.execute(
                        RuntimeBase.metadata.tables["attempts"]
                        .update()
                        .where(
                            RuntimeBase.metadata.tables["attempts"].c.attempt_id
                            == ids.root_attempt_id
                        )
                        .values(current_wait_id=ATTEMPT_WAIT_ID)
                    )
    finally:
        engine.dispose()


def test_attempt_wait_owns_one_exact_human_request_source(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            _close_current_dispatch(connection, ids)
            _insert_human_request(connection, ids)
            connection.execute(
                RuntimeBase.metadata.tables["attempt_waits"].insert(),
                _attempt_wait_row(ids, human_request_id=HUMAN_REQUEST_ID),
            )
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
                .values(
                    current_dispatch_id=None,
                    current_wait_id=ATTEMPT_WAIT_ID,
                )
            )

        with engine.connect() as connection:
            attempt = connection.execute(
                select(
                    RuntimeBase.metadata.tables["attempts"].c.current_dispatch_id,
                    RuntimeBase.metadata.tables["attempts"].c.current_wait_id,
                ).where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
            ).one()

        assert attempt.current_dispatch_id is None
        assert attempt.current_wait_id == ATTEMPT_WAIT_ID
    finally:
        engine.dispose()


def test_sequential_wait_rejects_child_from_another_dispatch(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            _close_current_dispatch(connection, ids)
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
                .values(current_dispatch_id=None)
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    RuntimeBase.metadata.tables["attempt_waits"].insert(),
                    _attempt_wait_row(
                        ids,
                        sequential_child_assignment_id=ids.child_assignment_id,
                    ),
                )
                connection.execute(
                    RuntimeBase.metadata.tables["attempts"]
                    .update()
                    .where(
                        RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id
                    )
                    .values(current_wait_id=ATTEMPT_WAIT_ID)
                )
    finally:
        engine.dispose()


def test_temporary_sequential_wait_accepts_exact_authored_child(tmp_path: Path) -> None:
    # WP07_SEQUENTIAL_DELEGATION_WAIT: WP-08 must replace this bridge with a Wave.
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            _close_current_dispatch(connection, ids)
            connection.execute(
                RuntimeBase.metadata.tables["attempt_waits"].insert(),
                _attempt_wait_row(
                    ids,
                    source_dispatch_id=ids.root_dispatch_id,
                    sequential_child_assignment_id=ids.child_assignment_id,
                ),
            )
            connection.execute(
                RuntimeBase.metadata.tables["attempts"]
                .update()
                .where(RuntimeBase.metadata.tables["attempts"].c.attempt_id == ids.root_attempt_id)
                .values(
                    current_dispatch_id=None,
                    current_wait_id=ATTEMPT_WAIT_ID,
                )
            )

        with engine.connect() as connection:
            wait_source = connection.execute(
                select(
                    RuntimeBase.metadata.tables["attempt_waits"].c.source_dispatch_id,
                    RuntimeBase.metadata.tables["attempt_waits"].c.sequential_child_assignment_id,
                )
            ).one()

        assert wait_source == (ids.root_dispatch_id, ids.child_assignment_id)
    finally:
        engine.dispose()


def test_accepted_boundary_links_cross_attempt_successor_directly(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                RuntimeBase.metadata.tables["accepted_boundaries"].insert(),
                {
                    "accepted_boundary_id": "boundary.child.green",
                    "source_dispatch_id": ids.child_dispatch_id,
                    "task_id": ids.task_id,
                    "flow_id": ids.flow_id,
                    "assignment_id": ids.child_assignment_id,
                    "attempt_id": ids.child_attempt_id,
                    "outcome": "green",
                    "checkpoint_id": ids.child_checkpoint_id,
                    "assignment_decision_id": None,
                    "successor_dispatch_id": ids.current_dispatch_id,
                    "committed_at": NOW,
                },
            )

        with engine.connect() as connection:
            successor_id = connection.scalar(
                select(RuntimeBase.metadata.tables["accepted_boundaries"].c.successor_dispatch_id)
            )

        assert successor_id == ids.current_dispatch_id
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_enforces_attempt_lane_schema() -> None:
    database_url = _disposable_postgres_url()
    if database_url is None:
        pytest.skip("a disposable PostgreSQL test database is not configured")

    schema_name = f"banksia_attempt_lane_{uuid4().hex}"
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
            await connection.run_sync(
                lambda sync_connection: verify_schema_contract(sync_connection, schema_name)
            )
            ids = await connection.run_sync(_seed_runtime_scope)

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: _close_current_dispatch(sync_connection, ids)
                )
    finally:
        if schema_created:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await engine.dispose()


def _dispatch_row(
    connection: Connection,
    ids: RuntimeIds,
    *,
    dispatch_id: str,
    assignment_id: str,
    attempt_id: str,
    node_key: str,
    predecessor_dispatch_id: str | None,
    status: str,
    opened_reason: str,
) -> dict[str, object]:
    source = (
        connection.execute(
            select(RuntimeBase.metadata.tables["dispatch_turns"]).where(
                RuntimeBase.metadata.tables["dispatch_turns"].c.dispatch_id
                == ids.current_dispatch_id
            )
        )
        .mappings()
        .one()
    )
    row = {key: value for key, value in source.items() if key not in {"active_status_marker"}}
    row.update(
        {
            "dispatch_id": dispatch_id,
            "assignment_id": assignment_id,
            "attempt_id": attempt_id,
            "node_key": node_key,
            "flow_node_id": ids.root_node_id if node_key == "root" else ids.child_node_id,
            "member_id": node_key,
            "member_configuration_id": member_configuration_id(ids, node_key),
            "member_branch_basis_id": member_branch_basis_id(ids, node_key),
            "flow_start_source_flow_id": None,
            "predecessor_dispatch_id": predecessor_dispatch_id,
            "status": status,
            "opened_reason": opened_reason,
            "adapter_started_at": NOW,
            "closed_at": NOW if status == "closed" else None,
            "closed_reason": "boundary" if status == "closed" else None,
        }
    )
    return row


def _close_current_dispatch(connection: Connection, ids: RuntimeIds) -> None:
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


def _insert_human_request(connection: Connection, ids: RuntimeIds) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["human_requests"].insert(),
        {
            "request_id": HUMAN_REQUEST_ID,
            "task_id": ids.task_id,
            "flow_id": ids.flow_id,
            "assignment_id": ids.root_assignment_id,
            "attempt_id": ids.root_attempt_id,
            "source_dispatch_id": ids.current_dispatch_id,
            "request_kind": "approval",
            "request_summary": "Approve the target transition.",
            "request_items_json": [{"id": "choice", "prompt": "Approve?"}],
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
        },
    )


def _attempt_wait_row(
    ids: RuntimeIds,
    *,
    source_dispatch_id: str | None = None,
    sequential_child_assignment_id: str | None = None,
    human_request_id: str | None = None,
) -> dict[str, object]:
    return {
        "wait_id": ATTEMPT_WAIT_ID,
        "task_id": ids.task_id,
        "flow_id": ids.flow_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": source_dispatch_id or ids.current_dispatch_id,
        "sequential_child_assignment_id": sequential_child_assignment_id,
        "human_request_id": human_request_id,
        "command_run_id": None,
        "created_at": NOW,
    }


def _seed_runtime_scope(connection: Connection) -> RuntimeIds:
    seed_catalog(connection)
    return seed_runtime_scope(connection)


def _run_starting_dispatch_writer(
    session_factory: SyncSessionFactory,
    ids: RuntimeIds,
    dispatch_id: str,
    barrier: Barrier,
) -> bool:
    barrier.wait(timeout=5)
    return asyncio.run(
        _stage_starting_dispatch(
            session_factory,
            ids,
            dispatch_id,
        )
    )


async def _stage_starting_dispatch(
    session_factory: SyncSessionFactory,
    ids: RuntimeIds,
    dispatch_id: str,
) -> bool:
    async with SyncSessionAdapter(session_factory) as session:
        try:
            await stage_starting_dispatch(
                cast(AsyncSession, session),
                basis=_starting_dispatch_basis(ids),
                prepared=_prepared_starting_dispatch(dispatch_id),
            )
            await session.commit()
        except AttemptDispatchConflictError:
            await session.rollback()
            return False
    return True


def _starting_dispatch_basis(ids: RuntimeIds) -> StartingDispatchBasis:
    return StartingDispatchBasis(
        task_id=ids.task_id,
        flow_id=ids.flow_id,
        assignment_id=ids.root_assignment_id,
        flow_revision_id=ids.flow_revision_id,
        flow_node_id=ids.root_node_id,
        team_revision_id=team_revision_id(ids),
        member_id="root",
        member_configuration_id=member_configuration_id(ids, "root"),
        member_branch_basis_id=member_branch_basis_id(ids, "root"),
        attempt_id=ids.root_attempt_id,
        node_key="root",
        opened_reason="human_result",
        predecessor_dispatch_id=ids.current_dispatch_id,
        flow_start_source_flow_id=None,
    )


def _prepared_starting_dispatch(dispatch_id: str) -> PreparedDispatchRequest:
    return PreparedDispatchRequest(
        dispatch_id=dispatch_id,
        due_at=NOW,
        provider=ProviderResolution(
            requested_provider=ProviderKind.CODEX,
            resolved_provider=ProviderKind.CODEX,
            selection_basis=ProviderSelectionBasis.DEFAULT,
            route=CodexProviderRoute(kind=ProviderKind.CODEX),
            sandbox=ManagedSandboxResolution(
                requested_mode=ManagedSandboxMode.FULL_ACCESS,
                requested_network=NetworkAccess.ALLOW,
                requested_source=SandboxResolutionSource.DEFAULT,
                effective_mode=ManagedSandboxMode.FULL_ACCESS,
                effective_network=NetworkAccess.ALLOW,
                effective_mode_source=SandboxResolutionSource.DEFAULT,
                effective_network_source=SandboxResolutionSource.DEFAULT,
            ),
            model_source=ProviderRouteValueSource.PROVIDER_CONFIGURATION,
            effort_source=ProviderRouteValueSource.PROVIDER_CONFIGURATION,
            gateway_profile_source=None,
        ),
        capabilities=EffectiveCapabilitySet(),
        instructions="Controller instructions.\n",
        input="<banksia_dispatch_request><direct_team /></banksia_dispatch_request>\n",
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

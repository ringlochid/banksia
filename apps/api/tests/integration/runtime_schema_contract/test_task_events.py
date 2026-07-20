from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest
from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.models import TaskEventModel, TaskEventStreamHeadModel, TaskModel
from autoclaw.persistence.models.runtime.common import (
    TASK_EVENT_SOURCE_VALUES,
    TASK_EVENT_TYPE_VALUES,
)
from autoclaw.runtime.contracts import TaskEventListResponse, TaskEventRecord
from autoclaw.runtime.task_events import (
    TaskEventStreamIntegrityError,
    append_task_event,
    compute_task_event_hash,
    encode_task_event_cursor,
    list_task_events,
    task_event_record_from_model,
)
from sqlalchemy import Engine, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
CANONICAL_SOURCES = {"controller", "control_api", "operator_mcp", "node"}
CANONICAL_TYPES = {
    "task_started",
    "dispatch_opened",
    "dispatch_start_updated",
    "work_plan_set",
    "work_plan_cleared",
    "checkpoint_recorded",
    "boundary_accepted",
    "child_assignment_staged",
    "child_assignment_committed",
    "structural_revision_adopted",
    "human_request_opened",
    "human_request_resolved",
    "human_request_timed_out",
    "human_request_cancelled",
    "command_run_opened",
    "command_run_started",
    "command_run_progressed",
    "command_run_cancel_requested",
    "command_run_succeeded",
    "command_run_failed",
    "command_run_timed_out",
    "command_run_cancelled",
    "command_run_abandoned",
    "task_paused",
    "task_resumed",
    "task_cancelled",
}


def _sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _checkpoint_payload(ids: RuntimeIds, actor_ref: str) -> dict[str, object]:
    return {
        "checkpoint_id": f"checkpoint.event.{actor_ref}",
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "checkpoint_kind": "progress",
        "outcome": None,
        "summary": f"Checkpoint recorded by {actor_ref}.",
        "checkpoint_ref": (f"_runtime/attempts/{ids.root_attempt_id}/latest-checkpoint.md"),
        "produced_artifacts": [],
        "transient_surfaces": [],
        "authored_by_dispatch_id": ids.current_dispatch_id,
    }


def _append_committed_event(
    factory: sessionmaker[Session],
    *,
    ids: RuntimeIds,
    actor_ref: str,
    barrier: Barrier | None = None,
) -> TaskEventRecord:
    if barrier is not None:
        barrier.wait()

    async def append_and_commit() -> TaskEventRecord:
        async with SyncSessionAdapter(factory) as session:
            record = await append_task_event(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                event_type="checkpoint_recorded",
                event_source="controller",
                actor_ref=actor_ref,
                payload=_checkpoint_payload(ids, actor_ref),
            )
            await session.commit()
            return record

    return asyncio.run(append_and_commit())


def test_task_event_sources_and_types_are_the_canonical_closed_sets() -> None:
    assert set(TASK_EVENT_SOURCE_VALUES) == CANONICAL_SOURCES
    assert set(TASK_EVENT_TYPE_VALUES) == CANONICAL_TYPES


def test_every_canonical_task_event_source_and_type_persists(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            events = RuntimeBase.metadata.tables["task_events"]
            rows = []
            event_seq = 1
            previous_hash = None
            for event_source in sorted(CANONICAL_SOURCES):
                for event_type in sorted(CANONICAL_TYPES):
                    event_hash = f"sha256:{event_seq}"
                    rows.append(
                        {
                            "event_id": f"event.{event_seq}",
                            "event_seq": event_seq,
                            "task_id": ids.task_id,
                            "event_type": event_type,
                            "event_source": event_source,
                            "occurred_at": NOW,
                            "flow_revision_id": None,
                            "dispatch_id": None,
                            "attempt_id": None,
                            "node_key": None,
                            "actor_ref": None,
                            "payload": {},
                            "prev_event_hash": previous_hash,
                            "event_hash": event_hash,
                        }
                    )
                    previous_hash = event_hash
                    event_seq += 1
            connection.execute(events.insert(), rows)
            connection.execute(
                RuntimeBase.metadata.tables["task_event_stream_heads"]
                .update()
                .where(
                    RuntimeBase.metadata.tables["task_event_stream_heads"].c.task_id == ids.task_id
                )
                .values(
                    allocator_revision=len(rows),
                    last_event_seq=len(rows),
                    last_event_hash=previous_hash,
                )
            )
        with engine.connect() as connection:
            count = connection.scalar(select(func.count()).select_from(events))
        assert count == len(CANONICAL_SOURCES) * len(CANONICAL_TYPES)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("column_name", "invalid_value"),
    (
        ("event_source", "provider"),
        ("event_source", "adapter"),
        ("event_type", "provider_completed"),
        ("event_type", "dispatch_provider_output"),
    ),
)
def test_noncanonical_provider_events_are_rejected(
    tmp_path: Path,
    column_name: str,
    invalid_value: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        row: dict[str, object] = {
            "event_id": "event.invalid",
            "event_seq": 1,
            "task_id": ids.task_id,
            "event_type": "task_started",
            "event_source": "controller",
            "occurred_at": NOW,
            "flow_revision_id": None,
            "dispatch_id": None,
            "attempt_id": None,
            "node_key": None,
            "actor_ref": None,
            "payload": {},
            "prev_event_hash": None,
            "event_hash": "sha256:invalid",
        }
        row[column_name] = invalid_value
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(RuntimeBase.metadata.tables["task_events"].insert(), row)
    finally:
        engine.dispose()


@pytest.mark.parametrize("event_seq", (0, -1))
def test_task_event_sequence_is_positive(tmp_path: Path, event_seq: int) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    RuntimeBase.metadata.tables["task_events"].insert(),
                    {
                        "event_id": f"event.invalid.{event_seq}",
                        "event_seq": event_seq,
                        "task_id": ids.task_id,
                        "event_type": "task_started",
                        "event_source": "controller",
                        "occurred_at": NOW,
                        "payload": {},
                        "event_hash": "sha256:invalid",
                    },
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "head_values",
    (
        {"allocator_revision": -1},
        {"last_event_seq": -1},
        {"last_event_seq": 1, "last_event_hash": None},
        {"last_event_seq": 0, "last_event_hash": "sha256:orphan"},
    ),
)
def test_task_event_stream_head_rejects_invalid_persisted_state(
    tmp_path: Path,
    head_values: dict[str, object],
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    update(TaskEventStreamHeadModel)
                    .where(TaskEventStreamHeadModel.task_id == ids.task_id)
                    .values(**head_values)
                )
    finally:
        engine.dispose()


def test_append_uses_only_the_chronology_head_as_its_allocator(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_statement(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        is_executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, is_executemany
        statements.append(statement)

    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        statements.clear()

        record = _append_committed_event(
            _sync_session_factory(engine),
            ids=ids,
            actor_ref="controller.first",
        )

        assert record.event_seq == 1
        assert any("UPDATE task_event_stream_heads" in statement for statement in statements)
        forbidden_authority_table = re.compile(r"\b(?:tasks|flows|dispatch_turns)\b")
        assert not any(forbidden_authority_table.search(statement) for statement in statements)
    finally:
        engine.dispose()


def test_concurrent_appends_commit_one_strict_sequence_and_hash_chain(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        factory = _sync_session_factory(engine)
        barrier = Barrier(2)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(
                executor.submit(
                    _append_committed_event,
                    factory,
                    ids=ids,
                    actor_ref=actor_ref,
                    barrier=barrier,
                )
                for actor_ref in ("controller.a", "controller.b")
            )
            records = tuple(future.result(timeout=10) for future in futures)

        with Session(engine) as session:
            rows = list(
                session.scalars(
                    select(TaskEventModel)
                    .where(TaskEventModel.task_id == ids.task_id)
                    .order_by(TaskEventModel.event_seq)
                )
            )
            head = session.get(TaskEventStreamHeadModel, ids.task_id)

        assert sorted(record.event_seq for record in records) == [1, 2]
        assert [row.event_seq for row in rows] == [1, 2]
        assert rows[0].prev_event_hash is None
        assert rows[1].prev_event_hash == rows[0].event_hash
        assert all(
            row.event_hash == compute_task_event_hash(task_event_record_from_model(row))
            for row in rows
        )
        assert head is not None
        assert head.allocator_revision == 2
        assert head.last_event_seq == 2
        assert head.last_event_hash == rows[1].event_hash
    finally:
        engine.dispose()


def test_rolled_back_append_does_not_consume_sequence_or_change_hash_head(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        factory = _sync_session_factory(engine)

        async def append_then_rollback() -> None:
            async with SyncSessionAdapter(factory) as session:
                await append_task_event(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    event_type="checkpoint_recorded",
                    event_source="controller",
                    payload=_checkpoint_payload(ids, "controller.rollback"),
                )
                await session.rollback()

        asyncio.run(append_then_rollback())
        committed = _append_committed_event(
            factory,
            ids=ids,
            actor_ref="controller.after-rollback",
        )

        with Session(engine) as session:
            rows = list(session.scalars(select(TaskEventModel)))
            head = session.get(TaskEventStreamHeadModel, ids.task_id)
        assert committed.event_seq == 1
        assert len(rows) == 1
        assert head is not None and head.allocator_revision == 1
        assert head.last_event_seq == 1
        assert head.last_event_hash == rows[0].event_hash
    finally:
        engine.dispose()


def test_append_rejects_a_missing_stream_head_without_touching_task(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                RuntimeBase.metadata.tables["task_event_stream_heads"]
                .delete()
                .where(
                    RuntimeBase.metadata.tables["task_event_stream_heads"].c.task_id == ids.task_id
                )
            )
        factory = _sync_session_factory(engine)

        with pytest.raises(TaskEventStreamIntegrityError, match="stream head is missing"):
            _append_committed_event(factory, ids=ids, actor_ref="controller.missing")

        with Session(engine) as session:
            assert session.get(TaskModel, ids.task_id) is not None
            assert session.scalar(select(func.count()).select_from(TaskEventModel)) == 0
    finally:
        engine.dispose()


def test_append_rejects_a_head_that_does_not_match_persisted_chronology(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                update(TaskEventStreamHeadModel)
                .where(TaskEventStreamHeadModel.task_id == ids.task_id)
                .values(allocator_revision=1)
            )
        factory = _sync_session_factory(engine)

        with pytest.raises(TaskEventStreamIntegrityError, match="does not match chronology"):
            _append_committed_event(factory, ids=ids, actor_ref="controller.corrupt")

        with Session(engine) as session:
            head = session.get(TaskEventStreamHeadModel, ids.task_id)
            assert head is not None and head.allocator_revision == 1
            assert head.last_event_seq == 0
            assert head.last_event_hash is None
            assert session.scalar(select(func.count()).select_from(TaskEventModel)) == 0
    finally:
        engine.dispose()


def test_task_event_reads_resume_exclusively_and_stop_at_high_water_mark(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        factory = _sync_session_factory(engine)
        records = tuple(
            _append_committed_event(factory, ids=ids, actor_ref=f"controller.{index}")
            for index in range(1, 5)
        )

        async def read_pages() -> tuple[TaskEventListResponse, TaskEventListResponse]:
            async with SyncSessionAdapter(factory) as session:
                first_page = await list_task_events(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    limit=1,
                )
                resumed_page = await list_task_events(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    cursor=first_page.next_cursor,
                    through_event_id=records[2].event_id,
                )
            return first_page, resumed_page

        first_page, resumed_page = asyncio.run(read_pages())

        assert [item.event_id for item in first_page.items] == [records[0].event_id]
        assert first_page.next_cursor is not None
        assert [item.event_id for item in resumed_page.items] == [
            records[1].event_id,
            records[2].event_id,
        ]
        assert records[3].event_id not in {item.event_id for item in resumed_page.items}
        assert resumed_page.next_cursor is None
    finally:
        engine.dispose()


def test_task_event_cursor_rejects_an_unknown_event_for_the_task(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        factory = _sync_session_factory(engine)
        _append_committed_event(factory, ids=ids, actor_ref="controller.first")

        async def read_unknown_cursor() -> None:
            async with SyncSessionAdapter(factory) as session:
                await list_task_events(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    cursor=encode_task_event_cursor("task-event.missing.00000001"),
                )

        with pytest.raises(ValueError, match="cursor_reset_required"):
            asyncio.run(read_unknown_cursor())
    finally:
        engine.dispose()

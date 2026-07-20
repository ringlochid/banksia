from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from autoclaw.config import CodexSettings, Settings
from autoclaw.persistence.models import DispatchPromptRefsModel, DispatchTurnModel, TaskModel
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.dispatch.cleanup import (
    DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE,
    cleanup_aged_dispatch_request_directories,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.dispatch.request_pair import publish_dispatch_request_pair
from autoclaw.runtime.launch.continuation import open_root_dispatch
from autoclaw.runtime.launch.persistence.runtime import persist_bootstrap_runtime_from_precomputed
from autoclaw.runtime.post_commit import CapturedRuntimeEffectPublisher, FlowStartCommitted
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.launch_foundation import (
    build_launch_foundation_definitions,
    build_launch_foundation_input,
    seed_launch_foundation_catalog,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)

_NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)

type SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def test_cleanup_removes_only_aged_unreferenced_publisher_directories(
    tmp_path: Path,
) -> None:
    data_boundary = tmp_path / "data"
    task_root = data_boundary / "tasks" / "task-cleanup"
    engine = create_runtime_schema_engine(tmp_path, name="request-cleanup.sqlite")
    session_context = _session_context(engine)
    await _insert_task(session_context, task_id="task-cleanup", task_root=task_root)
    paths = _task_root_paths(task_root)

    aged_candidate = _publish_pair(paths, "dispatch.aged")
    young_candidate = _publish_pair(paths, "dispatch.young")
    interrupted_stage = paths.dispatch_path / ".dispatch-stage-interrupted"
    interrupted_stage.mkdir()
    (interrupted_stage / "instructions.md").write_bytes(b"partial")
    durable_publication = paths.artifacts_path / "worker" / "result" / "publication.txt"
    durable_publication.parent.mkdir(parents=True)
    durable_publication.write_bytes(b"must remain outside request cleanup")

    _set_age(aged_candidate, _NOW - DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE)
    _set_age(interrupted_stage, _NOW - DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE)
    _set_age(young_candidate, _NOW - DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE + timedelta(seconds=1))
    _set_age(durable_publication, _NOW - timedelta(days=30))

    try:
        first = await cleanup_aged_dispatch_request_directories(
            session_factory=session_context,
            data_boundary=data_boundary,
            now=_NOW,
        )
        second = await cleanup_aged_dispatch_request_directories(
            session_factory=session_context,
            data_boundary=data_boundary,
            now=_NOW,
        )
    finally:
        engine.dispose()

    assert first.task_count == 1
    assert first.deleted_candidate_count == 1
    assert first.deleted_staging_count == 1
    assert first.young_count == 1
    assert not aged_candidate.exists()
    assert not interrupted_stage.exists()
    assert young_candidate.is_dir()
    assert durable_publication.read_bytes() == b"must remain outside request cleanup"
    assert second.deleted_candidate_count == 0
    assert second.deleted_staging_count == 0
    assert second.young_count == 1


async def test_cleanup_preserves_a_committed_dispatch_request_pair(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="request-cleanup-reference.sqlite")
    role, policy, workflow = build_launch_foundation_definitions()
    assert workflow.root.provider is not None
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        role=role,
        policy=policy,
        workflow=workflow,
    )
    with engine.begin() as connection:
        seed_launch_foundation_catalog(
            connection,
            role=role,
            policy=policy,
            workflow=workflow,
        )
    session_context = _session_context(engine)
    dependencies = DispatchOpeningDependencies.create(
        settings=Settings(codex=CodexSettings(enabled=True)),
        available_adapter_kinds={workflow.root.provider.kind},
        post_commit_publisher=CapturedRuntimeEffectPublisher(should_accept=False),
    )

    try:
        async with session_context() as session:
            await persist_bootstrap_runtime_from_precomputed(
                session,
                bootstrap_input,
            )
            opened = await open_root_dispatch(
                session,
                signal=FlowStartCommitted("flow.task.launch-foundation"),
                dependencies=dependencies,
            )
            dispatch = await session.scalar(select(DispatchTurnModel))
            refs = await session.scalar(select(DispatchPromptRefsModel))
        assert opened.outcome == "opened"
        assert dispatch is not None and refs is not None
        request_directory = bootstrap_input.task_root / Path(refs.input_logical_path).parent
        _set_age(
            request_directory,
            _NOW - DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE - timedelta(days=30),
        )

        result = await cleanup_aged_dispatch_request_directories(
            session_factory=session_context,
            data_boundary=tmp_path,
            now=_NOW,
        )
    finally:
        engine.dispose()

    assert result.referenced_count == 1
    assert result.deleted_candidate_count == 0
    assert request_directory.is_dir()
    assert (request_directory / "instructions.md").is_file()
    assert (request_directory / "input.md").is_file()


async def test_cleanup_rejects_symlinked_or_unexpected_request_entries(tmp_path: Path) -> None:
    data_boundary = tmp_path / "data"
    task_root = data_boundary / "tasks" / "task-unsafe"
    engine = create_runtime_schema_engine(tmp_path, name="request-cleanup-unsafe.sqlite")
    session_context = _session_context(engine)
    await _insert_task(session_context, task_id="task-unsafe", task_root=task_root)
    paths = _task_root_paths(task_root)
    paths.dispatch_path.mkdir(parents=True)

    external_directory = tmp_path / "external"
    external_directory.mkdir()
    (external_directory / "keep.txt").write_text("keep", encoding="utf-8")
    symlinked_candidate = paths.dispatch_path / "dispatch.symlink"
    symlinked_candidate.symlink_to(external_directory, target_is_directory=True)
    unexpected_candidate = paths.dispatch_path / "dispatch.unexpected"
    unexpected_candidate.mkdir()
    (unexpected_candidate / "not-a-request-file").write_text("keep", encoding="utf-8")
    _set_age(unexpected_candidate, _NOW - timedelta(days=2))

    try:
        result = await cleanup_aged_dispatch_request_directories(
            session_factory=session_context,
            data_boundary=data_boundary,
            now=_NOW,
        )
    finally:
        engine.dispose()

    assert result.rejected_count == 2
    assert symlinked_candidate.is_symlink()
    assert unexpected_candidate.is_dir()
    assert (external_directory / "keep.txt").read_text(encoding="utf-8") == "keep"


async def test_cleanup_rejects_a_task_root_outside_the_data_boundary(tmp_path: Path) -> None:
    data_boundary = tmp_path / "data"
    escaped_task_root = tmp_path / "outside" / "task-escape"
    engine = create_runtime_schema_engine(tmp_path, name="request-cleanup-escape.sqlite")
    session_context = _session_context(engine)
    await _insert_task(
        session_context,
        task_id="task-escape",
        task_root=escaped_task_root,
    )
    escaped_candidate = _publish_pair(
        _task_root_paths(escaped_task_root),
        "dispatch.escape",
    )
    _set_age(escaped_candidate, _NOW - timedelta(days=2))

    try:
        with pytest.raises(ValueError, match="escapes the configured data boundary"):
            await cleanup_aged_dispatch_request_directories(
                session_factory=session_context,
                data_boundary=data_boundary,
                now=_NOW,
            )
    finally:
        engine.dispose()

    assert escaped_candidate.is_dir()


async def test_cleanup_rejects_a_retention_window_below_the_canon_minimum(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="request-cleanup-horizon.sqlite")
    session_context = _session_context(engine)
    try:
        with pytest.raises(ValueError, match="at least 24 hours"):
            await cleanup_aged_dispatch_request_directories(
                session_factory=session_context,
                data_boundary=tmp_path,
                now=_NOW,
                minimum_age=timedelta(hours=23, minutes=59),
            )
    finally:
        engine.dispose()


def _session_context(engine: Engine) -> SessionContextFactory:
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def session_context() -> AbstractAsyncContextManager[AsyncSession]:
        return cast(AbstractAsyncContextManager[AsyncSession], SyncSessionAdapter(sync_factory))

    return session_context


async def _insert_task(
    session_context: SessionContextFactory,
    *,
    task_id: str,
    task_root: Path,
) -> None:
    async with session_context() as session:
        session.add(
            TaskModel(
                task_id=task_id,
                task_key=task_id,
                title="Cleanup test",
                summary="Prove reference-safe request cleanup.",
                instruction=None,
                workflow_key=None,
                task_root_path=str(task_root),
            )
        )
        await session.commit()


def _publish_pair(paths: TaskRootPaths, dispatch_id: str) -> Path:
    publish_dispatch_request_pair(
        paths=paths,
        dispatch_id=dispatch_id,
        instructions_bytes=b"instructions",
        input_bytes=b"input",
    )
    return paths.dispatch_path / dispatch_id


def _set_age(path: Path, changed_at: datetime) -> None:
    timestamp_ns = int(changed_at.timestamp() * 1_000_000_000)
    os.utime(path, ns=(timestamp_ns, timestamp_ns), follow_symlinks=False)


def _task_root_paths(task_root: Path) -> TaskRootPaths:
    runtime_path = task_root / "_runtime"
    outputs_path = task_root / "outputs"
    transfers_path = task_root / "tmp" / "transfers"
    return TaskRootPaths(
        task_root=task_root,
        workspace_path=task_root / "workspace",
        outputs_path=outputs_path,
        artifacts_path=outputs_path / "artifacts",
        tmp_path=task_root / "tmp",
        transfers_path=transfers_path,
        localized_path=transfers_path / "localized",
        runtime_path=runtime_path,
        criteria_path=runtime_path / "criteria",
        attempts_path=runtime_path / "attempts",
        dispatch_path=runtime_path / "dispatch",
    )

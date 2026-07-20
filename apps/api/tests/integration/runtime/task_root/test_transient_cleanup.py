from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence.models import FlowModel, TransientLocalizationModel
from autoclaw.runtime.flow.service import cancel_runtime_flow
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchCleanupRequested,
    TransientCleanupRequested,
)
from autoclaw.runtime.post_commit.bootstrap import read_transient_cleanup_page
from autoclaw.runtime.task_root import cleanup_expired_transient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_exact_expired_transient_cleanup_is_restartable_and_idempotent(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="transient-cleanup") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        signal, body_path = await _create_expired_transient(
            executor,
            session_factory,
            ids,
            task_root=tmp_path / "task-transient-cleanup",
        )
        page = await read_transient_cleanup_page(
            cast(
                Callable[[], AbstractAsyncContextManager[AsyncSession]],
                session_factory,
            ),
            None,
            200,
        )
        assert page.sources == (signal,)

        async with session_factory() as session:
            removed = await cleanup_expired_transient(cast(AsyncSession, session), signal)
        assert removed is True
        assert not body_path.exists()

        async with session_factory() as session:
            source = await session.get(
                TransientLocalizationModel,
                signal.transient_localization_id,
            )
            duplicate = await cleanup_expired_transient(cast(AsyncSession, session), signal)
        assert source is not None and source.retention_status == "removed"
        assert source.removed_at is not None
        assert duplicate is False


async def test_transient_cleanup_never_crosses_into_workspace(
    tmp_path: Path,
) -> None:
    task_root = tmp_path / "task-transient-workspace-preserved"
    async with seeded_executor(tmp_path, suffix="transient-workspace-preserved") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        signal, localized_body = await _create_expired_transient(
            executor,
            session_factory,
            ids,
            task_root=task_root,
        )
        external_body = task_root / "workspace" / "must-remain.txt"
        external_body.write_text("preserve me\n", encoding="utf-8")
        async with session_factory() as session:
            source = await session.get(
                TransientLocalizationModel,
                signal.transient_localization_id,
            )
            assert source is not None
            source.localized_logical_path = "workspace/must-remain.txt"
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ValueError, match="outside the localized transfer root"):
                await cleanup_expired_transient(cast(AsyncSession, session), signal)
            source = await session.get(
                TransientLocalizationModel,
                signal.transient_localization_id,
            )

        assert source is not None and source.retention_status == "expired"
        assert external_body.read_text(encoding="utf-8") == "preserve me\n"
        assert localized_body.exists()


async def test_active_transient_rejects_an_obsolete_cleanup_generation(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="transient-active") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        signal, body_path = await _create_expired_transient(
            executor,
            session_factory,
            ids,
            task_root=tmp_path / "task-transient-active",
        )
        async with session_factory() as session:
            source = await session.get(
                TransientLocalizationModel,
                signal.transient_localization_id,
            )
            assert source is not None
            source.retention_status = "active"
            await session.commit()

        async with session_factory() as session:
            removed = await cleanup_expired_transient(cast(AsyncSession, session), signal)
            source = await session.get(
                TransientLocalizationModel,
                signal.transient_localization_id,
            )

        assert removed is False
        assert source is not None and source.retention_status == "active"
        assert body_path.is_file()


async def test_task_cancel_publishes_only_exact_already_expired_transients(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="transient-cancel") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        signal, _ = await _create_expired_transient(
            executor,
            session_factory,
            ids,
            task_root=tmp_path / "task-transient-cancel",
        )
        async with session_factory() as session:
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=flow.control_revision,
                runtime_effect_publisher=publisher,
            )

    assert publisher.signals == (
        DispatchCleanupRequested(ids.current_dispatch_id),
        signal,
    )


async def _create_expired_transient(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    task_root: Path,
) -> tuple[TransientCleanupRequested, Path]:
    source_path = task_root / "workspace" / "transient.txt"
    source_path.write_text("temporary body\n", encoding="utf-8")
    result = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="record_checkpoint",
        arguments={
            "checkpoint": {
                "checkpoint_kind": "progress",
                "handoff": {"summary": "Transient ready.", "next_step": "Continue."},
                "transient_surfaces": [
                    {"path": "workspace/transient.txt", "description": "Temporary body."}
                ],
            }
        },
    )
    checkpoint_id = cast(str, result.model_dump()["checkpoint_id"])
    expires_at = datetime(2026, 7, 18, 12, tzinfo=UTC)
    async with session_factory() as session:
        transient = await session.scalar(
            select(TransientLocalizationModel).where(
                TransientLocalizationModel.checkpoint_id == checkpoint_id
            )
        )
        assert transient is not None
        transient.retention_status = "expired"
        transient.expires_at = expires_at
        transient_localization_id = transient.transient_localization_id
        localized_logical_path = transient.localized_logical_path
        await session.commit()

    async with session_factory() as session:
        transient = await session.get(
            TransientLocalizationModel,
            transient_localization_id,
        )
        assert transient is not None and transient.expires_at is not None
        signal = TransientCleanupRequested(
            transient_localization_id=transient.transient_localization_id,
            expires_at=transient.expires_at,
        )
        body_path = task_root / localized_logical_path
    assert body_path.is_file()
    return signal, body_path


__all__ = []

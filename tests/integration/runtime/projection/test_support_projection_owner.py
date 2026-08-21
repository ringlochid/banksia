from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.startup_audit as startup_audit
from oh_my_subagents.runtime.projection.materialization import project_workflow_manifest
from oh_my_subagents.runtime.projection.signals import (
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from oh_my_subagents.runtime.startup_audit import (
    AsyncSessionContextFactory,
    audit_startup_support_projections,
)
from tests.helpers.executor_harness import seeded_executor, seeded_task_root


async def test_manifest_is_the_only_retained_support_projection(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="support-manifest") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as raw_session:
            session = cast(AsyncSession, raw_session)
            assert await project_workflow_manifest(
                session,
                WorkflowManifestProjection(ids.task_id, ids.team_revision_id),
            )
            assert not await project_workflow_manifest(
                session,
                WorkflowManifestProjection(ids.task_id, "revision.stale"),
            )

    task_root = seeded_task_root(tmp_path, "support-manifest")
    manifest = (task_root / "manifest.md").read_text(encoding="utf-8")
    assert "# Oh My Subagents team" in manifest
    assert f"- Task: `{ids.task_id}`" in manifest
    assert "- Workflow: `workflow.target`" in manifest
    assert "- Lead: `root`" in manifest
    assert "`root` — Manager" in manifest
    assert "`child` — Contributor" in manifest
    assert "Active revision" not in manifest
    assert "Member configuration" not in manifest
    assert "Branch basis" not in manifest
    assert str(task_root) not in manifest
    assert not (task_root / "_runtime/attempts").exists()


async def test_startup_republishes_only_manifest_exact_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="support-audit") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        monkeypatch.setattr(startup_audit, "STARTUP_AUDIT_PAGE_SIZE", 1)
        signals: list[SupportProjectionSignal] = []
        typed_factory = cast(AsyncSessionContextFactory, session_factory)

        async def capture(signal: SupportProjectionSignal) -> bool:
            signals.append(signal)
            return True

        counts = await audit_startup_support_projections(
            session_factory=typed_factory,
            publish=capture,
        )
        first_pass = tuple(signals)
        second_counts = await audit_startup_support_projections(
            session_factory=typed_factory,
            publish=capture,
        )

    expected = WorkflowManifestProjection(ids.task_id, ids.team_revision_id)
    assert counts == second_counts == {"workflow_manifest_projection": 1}
    assert first_pass == (expected,)
    assert tuple(signals[len(first_pass) :]) == first_pass

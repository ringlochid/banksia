from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import autoclaw.runtime.startup_audit as startup_audit
import pytest
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AttemptModel,
    FlowNodeModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.projection.materialization import (
    project_artifact_index,
    project_attempt_assignment,
    project_criteria,
    project_latest_checkpoint,
    project_transient_index,
    project_workflow_manifest,
)
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    AttemptAssignmentProjection,
    CriteriaProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
    WorkflowManifestProjection,
)
from autoclaw.runtime.startup_audit import (
    AsyncSessionContextFactory,
    audit_startup_support_projections,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_all_support_handlers_write_logical_readbacks_and_reject_stale_sources(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="support-projections") as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _seed_projection_sources(session_factory, ids)
        task_root = tmp_path / "task-support-projections"
        await _project_all_support_sources(session_factory, ids)
        _assert_projected_readbacks(task_root, ids)
        await _assert_stale_sources_are_rejected(session_factory, task_root, ids)


async def _project_all_support_sources(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as raw_session:
        session = cast(AsyncSession, raw_session)
        assert await project_workflow_manifest(
            session,
            WorkflowManifestProjection(ids.flow_id, ids.flow_revision_id),
        )
        assert await project_criteria(
            session,
            CriteriaProjection(ids.flow_revision_id, "root", "criteria", 1),
        )
        assert await project_attempt_assignment(
            session,
            AttemptAssignmentProjection(
                ids.root_assignment_id,
                ids.root_attempt_id,
                ids.flow_revision_id,
            ),
        )
        assert await project_latest_checkpoint(
            session,
            LatestCheckpointProjection(ids.root_attempt_id, ids.root_checkpoint_id),
        )
        assert await project_artifact_index(
            session,
            ArtifactProjection("artifact.support.1", 1),
        )
        assert await project_transient_index(
            session,
            TransientProjection("transient.support.1"),
        )


def _assert_projected_readbacks(task_root: Path, ids: RuntimeIds) -> None:
    manifest = _read_json(task_root / "_runtime/workflow-manifest.json")
    attempt_root = task_root / f"_runtime/attempts/{ids.root_attempt_id}"
    assignment = _read_json(attempt_root / "assignment.json")
    checkpoint = _read_json(attempt_root / "latest-checkpoint.json")
    artifact_index = _read_json(attempt_root / "artifact-index.json")
    transient_index = _read_json(attempt_root / "transient-index.json")

    assert manifest["active_flow_revision_id"] == ids.flow_revision_id
    assert "filesystem_roots" not in manifest
    assert "current_context" not in manifest
    assert str(task_root) not in json.dumps(manifest)
    assert assignment["attempt_id"] == ids.root_attempt_id
    assert assignment["criteria"][0]["logical_path"] == "_runtime/criteria/root.md"
    assert checkpoint["checkpoint_id"] == ids.root_checkpoint_id
    assert checkpoint["artifacts"][0]["logical_path"] == "outputs/artifacts/root/result"
    assert artifact_index["publications"][0]["is_current"] is True
    assert transient_index["localizations"][0]["localized_logical_path"].startswith(
        "tmp/transfers/localized/"
    )


async def _assert_stale_sources_are_rejected(
    session_factory: SessionFactory,
    task_root: Path,
    ids: RuntimeIds,
) -> None:
    manifest_path = task_root / "_runtime/workflow-manifest.json"
    artifact_path = task_root / f"_runtime/attempts/{ids.root_attempt_id}/artifact-index.json"
    manifest_bytes = manifest_path.read_bytes()
    artifact_bytes = artifact_path.read_bytes()
    async with session_factory() as raw_session:
        session = cast(AsyncSession, raw_session)
        assert not await project_workflow_manifest(
            session,
            WorkflowManifestProjection(ids.flow_id, "revision.stale"),
        )
        assert not await project_criteria(
            session,
            CriteriaProjection(ids.flow_revision_id, "root", "criteria", 2),
        )
        assert not await project_attempt_assignment(
            session,
            AttemptAssignmentProjection(
                ids.root_assignment_id,
                "attempt.stale",
                ids.flow_revision_id,
            ),
        )
        assert not await project_artifact_index(
            session,
            ArtifactProjection("artifact.support.1", 2),
        )
    assert manifest_path.read_bytes() == manifest_bytes
    assert artifact_path.read_bytes() == artifact_bytes


async def test_startup_pages_and_republishes_all_six_exact_source_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="support-audit") as (
        _,
        session_factory,
        ids,
        _,
    ):
        await _seed_projection_sources(session_factory, ids)
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

    assert counts == second_counts
    assert counts["workflow_manifest_projection"] == 1
    assert counts["criteria_projection"] == 1
    assert counts["attempt_assignment_projection"] == 2
    assert counts["latest_checkpoint_projection"] == 1
    assert counts["artifact_projection"] == 1
    assert counts["transient_projection"] == 1
    assert tuple(signals[len(first_pass) :]) == first_pass


async def _seed_projection_sources(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    factory = cast(AsyncSessionContextFactory, session_factory)
    async with factory() as session:
        root_node = await session.get(FlowNodeModel, ids.root_node_id)
        root_attempt = await session.get(AttemptModel, ids.root_attempt_id)
        assert root_node is not None and root_attempt is not None
        root_node.criteria_json = [
            {
                "owner_node_key": "root",
                "slot": "criteria",
                "description": "Root criteria.",
                "criteria": ["Keep controller truth explicit."],
                "version": 1,
                "path": "_runtime/criteria/criteria.v01.md",
            }
        ]
        root_attempt.latest_checkpoint_id = ids.root_checkpoint_id
        session.add(
            ArtifactPublicationModel(
                artifact_publication_id="artifact.support.1",
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
                slot="result",
                version=1,
                logical_path="outputs/artifacts/root/result",
                description="Published result.",
            )
        )
        session.add(
            ArtifactCurrentPointerModel(
                artifact_current_pointer_id="artifact-current.support.result",
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                slot="result",
                current_publication_id="artifact.support.1",
                current_version=1,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
            )
        )
        session.add(
            TransientLocalizationModel(
                transient_localization_id="transient.support.1",
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
                source_logical_path="workspace/source.txt",
                localized_logical_path="tmp/transfers/localized/source.txt",
                description="Localized source.",
                retention_status="active",
                localized_at=utc_now(),
            )
        )
        await session.commit()


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

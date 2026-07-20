from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import autoclaw.runtime.node_operations.executor as executor_module
import autoclaw.runtime.task_root.file_access as file_access_module
import pytest
from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    CheckpointTransientModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.checkpoint import CheckpointPreparation
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeOperationScope, get_node_operation_descriptor
from autoclaw.runtime.node_operations.contracts import RecordCheckpointRequest
from pydantic import ValidationError
from sqlalchemy import func, select
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def _create_competing_artifact_pointer(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    publication_id = "artifact-publication.competing-b"
    async with session_factory() as session:
        session.add(
            ArtifactPublicationModel(
                artifact_publication_id=publication_id,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
                slot="b",
                version=1,
                logical_path="outputs/artifacts/root/b/competing.txt",
                description="Competing B.",
                supersedes_publication_id=None,
                supersedes_version=None,
            )
        )
        session.add(
            ArtifactCurrentPointerModel(
                artifact_current_pointer_id="artifact-current-pointer.competing-b",
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                slot="b",
                current_publication_id=publication_id,
                current_version=1,
                attempt_id=ids.root_attempt_id,
                checkpoint_id=ids.root_checkpoint_id,
            )
        )
        await session.commit()


def test_checkpoint_claim_paths_are_logical_strings() -> None:
    request_model = get_node_operation_descriptor("record_checkpoint").request_model
    request = cast(
        RecordCheckpointRequest,
        request_model.model_validate(
            {
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {"summary": "Ready.", "next_step": "Continue."},
                    "produced_artifacts": [{"slot": "report", "path": "workspace/./draft.md"}],
                }
            }
        ),
    )

    assert request.checkpoint.produced_artifacts[0].path == "workspace/draft.md"
    for value in ("/tmp/report", "../report", "workspace/../report", "C:/report"):
        with pytest.raises(ValidationError):
            request_model.model_validate(
                {
                    "checkpoint": {
                        "checkpoint_kind": "progress",
                        "handoff": {"summary": "Ready.", "next_step": "Continue."},
                        "transient_surfaces": [{"path": value, "description": "Invalid source."}],
                    }
                }
            )


async def test_checkpoint_atomically_persists_artifact_and_transient_bodies(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="body-publication") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        task_root = tmp_path / "task-body-publication"
        artifact_source = task_root / "workspace" / "report.md"
        transient_source = task_root / "workspace" / "run.log"
        artifact_source.write_text("durable report\n", encoding="utf-8")
        transient_source.write_text("temporary log\n", encoding="utf-8")
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [{"slot": "report", "description": "Published report."}]
            await session.commit()

        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "progress",
                    "handoff": {"summary": "Bodies ready.", "next_step": "Continue."},
                    "produced_artifacts": [{"slot": "report", "path": "workspace/report.md"}],
                    "transient_surfaces": [
                        {"path": "workspace/run.log", "description": "Command log."}
                    ],
                }
            },
        )
        checkpoint_id = result.model_dump()["checkpoint_id"]

        async with session_factory() as session:
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            publication = await session.scalar(
                select(ArtifactPublicationModel).where(
                    ArtifactPublicationModel.checkpoint_id == checkpoint_id
                )
            )
            pointer = await session.scalar(
                select(ArtifactCurrentPointerModel).where(
                    ArtifactCurrentPointerModel.assignment_id == ids.root_assignment_id,
                    ArtifactCurrentPointerModel.slot == "report",
                )
            )
            transient = await session.scalar(
                select(TransientLocalizationModel).where(
                    TransientLocalizationModel.checkpoint_id == checkpoint_id
                )
            )
            association = await session.scalar(
                select(CheckpointTransientModel).where(
                    CheckpointTransientModel.checkpoint_id == checkpoint_id
                )
            )

        assert attempt is not None and attempt.latest_checkpoint_id == checkpoint_id
        assert publication is not None and pointer is not None
        assert publication.version == 1
        assert pointer.current_publication_id == publication.artifact_publication_id
        assert pointer.checkpoint_id == checkpoint_id
        assert publication.logical_path.startswith("outputs/artifacts/root/report/")
        assert publication.logical_path.endswith(".md")
        assert (task_root / publication.logical_path).read_text(encoding="utf-8") == (
            "durable report\n"
        )
        assert transient is not None and association is not None
        assert transient.retention_status == "active"
        assert transient.localized_logical_path.startswith("tmp/transfers/localized/")
        assert (task_root / transient.localized_logical_path).read_text(encoding="utf-8") == (
            "temporary log\n"
        )
        assert association.transient_localization_id == transient.transient_localization_id


async def test_terminal_green_requires_every_declared_artifact_before_mutation(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-green-missing-output") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [
                {"slot": "report", "description": "Required report."},
            ]
            await session.commit()

        with pytest.raises(RuntimeOperationError) as missing:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="record_checkpoint",
                arguments={
                    "checkpoint": {
                        "checkpoint_kind": "terminal",
                        "outcome": "green",
                        "handoff": {
                            "summary": "The report was not published.",
                            "next_step": "Publish the required report.",
                        },
                    }
                },
            )

        async with session_factory() as session:
            checkpoint_count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
            publication_count = await session.scalar(
                select(func.count())
                .select_from(ArtifactPublicationModel)
                .where(ArtifactPublicationModel.assignment_id == ids.root_assignment_id)
            )

        assert missing.value.code == OperationFailureCode.MISSING_REQUIRED_PUBLICATION
        assert checkpoint_count == 0
        assert publication_count == 0


async def test_terminal_green_publishes_every_declared_artifact(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="terminal-green-complete-output") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        source = tmp_path / "task-terminal-green-complete-output" / "workspace" / "report.md"
        source.write_text("complete report\n", encoding="utf-8")
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [
                {"slot": "report", "description": "Required report."},
            ]
            await session.commit()

        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "green",
                    "handoff": {
                        "summary": "The report is complete.",
                        "next_step": "Return green.",
                    },
                    "produced_artifacts": [
                        {"slot": "report", "path": "workspace/report.md"},
                    ],
                }
            },
        )

        async with session_factory() as session:
            publication = await session.scalar(
                select(ArtifactPublicationModel).where(
                    ArtifactPublicationModel.checkpoint_id == result.model_dump()["checkpoint_id"]
                )
            )

        assert publication is not None
        assert publication.slot == "report"


async def test_artifact_versions_advance_from_the_exact_current_pointer(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="body-version") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        source = tmp_path / "task-body-version" / "workspace" / "report.txt"
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [{"slot": "report", "description": "Report."}]
            await session.commit()
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        for content in ("one\n", "two\n"):
            source.write_text(content, encoding="utf-8")
            await executor.execute(
                scope=scope,
                operation_name="record_checkpoint",
                arguments={
                    "checkpoint": {
                        "checkpoint_kind": "progress",
                        "handoff": {"summary": "Version ready.", "next_step": "Continue."},
                        "produced_artifacts": [{"slot": "report", "path": "workspace/report.txt"}],
                    }
                },
            )

        async with session_factory() as session:
            publications = tuple(
                await session.scalars(
                    select(ArtifactPublicationModel)
                    .where(ArtifactPublicationModel.assignment_id == ids.root_assignment_id)
                    .order_by(ArtifactPublicationModel.version)
                )
            )
            pointer = await session.scalar(
                select(ArtifactCurrentPointerModel).where(
                    ArtifactCurrentPointerModel.assignment_id == ids.root_assignment_id,
                    ArtifactCurrentPointerModel.slot == "report",
                )
            )

        assert [publication.version for publication in publications] == [1, 2]
        assert publications[1].supersedes_publication_id == publications[0].artifact_publication_id
        assert pointer is not None
        assert pointer.current_publication_id == publications[1].artifact_publication_id
        assert pointer.current_version == 2


async def test_source_mutation_rejects_checkpoint_and_cleans_only_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="body-mutation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        source = tmp_path / "task-body-mutation" / "workspace" / "report.bin"
        source.write_bytes(b"initial")
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [{"slot": "report", "description": "Report."}]
            await session.commit()
        real_read = os.read
        mutated = False

        def mutate_after_read(file_descriptor: int, length: int) -> bytes:
            nonlocal mutated
            payload = real_read(file_descriptor, length)
            if not mutated:
                with source.open("ab") as stream:
                    stream.write(b"-changed")
                mutated = True
            return payload

        monkeypatch.setattr(file_access_module.os, "read", mutate_after_read)
        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="record_checkpoint",
                arguments={
                    "checkpoint": {
                        "checkpoint_kind": "progress",
                        "handoff": {"summary": "Copy.", "next_step": "Continue."},
                        "produced_artifacts": [{"slot": "report", "path": "workspace/report.bin"}],
                    }
                },
            )

        async with session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
        assert mutated is True
        assert error.value.code == OperationFailureCode.CONFLICT
        assert count == 0
        publication_root = tmp_path / "task-body-mutation" / "outputs" / "artifacts"
        assert not tuple(path for path in publication_root.rglob("*") if path.is_file())


async def test_escaped_symlink_and_special_source_are_rejected(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="body-source-kind") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        task_root = tmp_path / "task-body-source-kind"
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"secret")
        (task_root / "workspace" / "escape.bin").symlink_to(outside)
        fifo = task_root / "workspace" / "stream"
        os.mkfifo(fifo)
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [{"slot": "report", "description": "Report."}]
            await session.commit()
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)

        for source, expected in (
            ("workspace/escape.bin", OperationFailureCode.PATH_ESCAPE),
            ("workspace/stream", OperationFailureCode.NOT_A_FILE),
        ):
            with pytest.raises(RuntimeOperationError) as error:
                await executor.execute(
                    scope=scope,
                    operation_name="record_checkpoint",
                    arguments={
                        "checkpoint": {
                            "checkpoint_kind": "progress",
                            "handoff": {"summary": "Copy.", "next_step": "Continue."},
                            "produced_artifacts": [{"slot": "report", "path": source}],
                        }
                    },
                )
            assert error.value.code == expected


async def test_real_pointer_race_rolls_back_all_rows_but_keeps_final_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="body-pointer-race") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        task_root = tmp_path / "task-body-pointer-race"
        (task_root / "workspace" / "a.txt").write_text("a", encoding="utf-8")
        (task_root / "workspace" / "b.txt").write_text("b", encoding="utf-8")
        async with session_factory() as session:
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
            assert assignment is not None
            assignment.produces_json = [
                {"slot": "a", "description": "A."},
                {"slot": "b", "description": "B."},
            ]
            await session.commit()
        real_publish = executor_module.publish_checkpoint_bodies

        async def publish_then_create_competing_pointer(
            preparation: CheckpointPreparation,
        ) -> CheckpointPreparation:
            prepared = await real_publish(preparation)
            await _create_competing_artifact_pointer(session_factory, ids)
            return prepared

        monkeypatch.setattr(
            executor_module,
            "publish_checkpoint_bodies",
            publish_then_create_competing_pointer,
        )
        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="record_checkpoint",
                arguments={
                    "checkpoint": {
                        "checkpoint_kind": "progress",
                        "handoff": {"summary": "Race.", "next_step": "Retry."},
                        "produced_artifacts": [
                            {"slot": "a", "path": "workspace/a.txt"},
                            {"slot": "b", "path": "workspace/b.txt"},
                        ],
                    }
                },
            )

        async with session_factory() as session:
            checkpoint_count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
            a_pointer = await session.scalar(
                select(ArtifactCurrentPointerModel).where(
                    ArtifactCurrentPointerModel.assignment_id == ids.root_assignment_id,
                    ArtifactCurrentPointerModel.slot == "a",
                )
            )
        assert error.value.code == OperationFailureCode.CONFLICT
        assert checkpoint_count == 0
        assert a_pointer is None
        final_candidates = tuple(
            path for path in (task_root / "outputs" / "artifacts").rglob("*") if path.is_file()
        )
        assert len(final_candidates) == 2

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import banksia.runtime.task_start as task_start_module
import banksia.runtime.workspace_admission as workspace_admission_module
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentFileReferenceModel,
    AssignmentModel,
    AttemptModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowRevisionModel,
    FlowStartSourceModel,
    TaskEventModel,
    TaskModel,
    TeamRevisionModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import FileReference, TaskStartRequest, TaskStartResponse
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import DispatchStartDue, RuntimeEffectSignal
from banksia.runtime.projection.materialization import project_workflow_manifest
from banksia.runtime.projection.signals import WorkflowManifestProjection
from banksia.runtime.task_start import start_task
from banksia.runtime.team import plan_initial_task_team
from banksia.runtime.workspace_admission import (
    TASK_INITIALIZATION_MARKER,
    recover_task_workspace_admissions,
    stage_task_workspace,
)
from banksia.workflows.authoring import create_workflow_draft, publish_workflow_draft
from banksia.workflows.catalog import read_current_published_workflow
from sqlalchemy import func, select
from tests.helpers.workflow_runtime import initialized_workflow_database

_TASK_ID_PATTERN = re.compile(r"t_[0-9abcdefghjkmnpqrstvwxyz]{8}\Z")


class _CommittedRuntimePublisher:
    def __init__(self, session: Any, *, should_raise: bool = False) -> None:
        self._session = session
        self._should_raise = should_raise
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        assert not self._session.in_transaction()
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("runtime publication unavailable")
        return True


@dataclass(frozen=True, slots=True)
class _StartedTaskState:
    task: TaskModel | None
    assignment: AssignmentModel | None
    file_rows: tuple[AssignmentFileReferenceModel, ...]
    attempt: AttemptModel | None
    dispatch: DispatchTurnModel | None
    prompt_refs: DispatchPromptRefsModel | None
    flow: FlowModel | None
    source: FlowStartSourceModel | None
    counts: tuple[int, ...]


async def test_task_start_commits_exact_assignment_and_dispatch_before_hint(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "brief.md").write_text("source brief", encoding="utf-8")
    request = TaskStartRequest.model_validate(
        {
            "workflow": "reviewed-delivery",
            "prompt": "Preserve  leading space.\r\nThen deliver.\r",
            "workspace": str(workspace),
            "files": [
                {"path": "./brief.md", "description": "Read this first."},
            ],
        }
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            publisher = _CommittedRuntimePublisher(session, should_raise=True)
            response = await start_task(
                request,
                session=session,
                dependencies=_dependencies(publisher, workspace=workspace),
            )
            started = await _read_started_task_state(session, task_id=response.task_id)
            task_root = workspace / ".banksia" / response.task_id
            initial_manifest = (task_root / "manifest.md").read_bytes()
            assert started.flow is not None and started.flow.active_flow_revision_id is not None
            assert await project_workflow_manifest(
                session,
                WorkflowManifestProjection(
                    started.flow.flow_id,
                    started.flow.active_flow_revision_id,
                ),
            )
            refreshed_manifest = (task_root / "manifest.md").read_bytes()

            current = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            draft = await create_workflow_draft(
                session,
                workflow=current.workflow.model_copy(
                    update={"description": "A later published Workflow revision."}
                ),
            )
            later = await publish_workflow_draft(
                session,
                draft_id=draft.draft_id,
                expected_etag=draft.etag,
            )
            await session.commit()
            pinned_task = await session.get(TaskModel, response.task_id)

    _assert_started_task_state(
        response=response,
        started=started,
        publisher=publisher,
        workspace=workspace,
    )
    assert later.revision_no == 2
    assert pinned_task is not None and pinned_task.workflow_revision_no == 1
    assert refreshed_manifest == initial_manifest
    _assert_started_task_workspace(task_root)


async def test_task_start_rejection_and_failed_transaction_leave_no_task_or_task_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            publisher = _CommittedRuntimePublisher(session)
            missing_file_request = TaskStartRequest(
                workflow="reviewed-delivery",
                prompt="Read the missing input.",
                workspace=workspace,
                files=(FileReference(path="missing.md"),),
            )
            with pytest.raises(
                RuntimeOperationError,
                match=r"referenced file does not exist: missing\.md",
            ) as missing_file:
                await start_task(
                    missing_file_request,
                    session=session,
                    dependencies=_dependencies(publisher, workspace=workspace),
                )
            assert missing_file.value.status_code_override == 422
            assert await _task_count(session) == 0
            assert publisher.signals == []
            assert not (workspace / ".banksia").exists()

            with pytest.raises(FileNotFoundError, match="missing-workflow"):
                await start_task(
                    _request(workspace, workflow="missing-workflow"),
                    session=session,
                    dependencies=_dependencies(publisher, workspace=workspace),
                )
            assert await _task_count(session) == 0
            assert publisher.signals == []
            assert not (workspace / ".banksia").exists()

            async def fail_after_runtime_staging(*args: object, **kwargs: object) -> object:
                del args, kwargs
                raise RuntimeError("dispatch staging failed")

            monkeypatch.setattr(
                task_start_module,
                "stage_initial_root_dispatch",
                fail_after_runtime_staging,
            )
            with pytest.raises(RuntimeError, match="dispatch staging failed"):
                await start_task(
                    _request(workspace),
                    session=session,
                    dependencies=_dependencies(publisher, workspace=workspace),
                )
            assert await _task_count(session) == 0
            assert publisher.signals == []
            banksia_root = workspace / ".banksia"
            assert not banksia_root.exists() or not tuple(banksia_root.glob("t_*"))


async def test_task_workspace_recovery_removes_only_uncommitted_markers(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=_dependencies(
                    _CommittedRuntimePublisher(session),
                    workspace=workspace,
                ),
            )
            committed_root = workspace / ".banksia" / response.task_id
            committed_marker = committed_root / TASK_INITIALIZATION_MARKER
            committed_marker.write_text(
                f"banksia-task-initialization-v1\n{response.task_id}\n",
                encoding="utf-8",
            )
            orphan_id = "t_01234567"
            orphan_root = workspace / ".banksia" / orphan_id
            orphan_root.mkdir()
            (orphan_root / TASK_INITIALIZATION_MARKER).write_text(
                f"banksia-task-initialization-v1\n{orphan_id}\n",
                encoding="utf-8",
            )

            recovered = await recover_task_workspace_admissions(
                session,
                workspaces=(workspace,),
            )

    assert committed_root in recovered
    assert orphan_root in recovered
    assert committed_root.is_dir()
    assert not committed_marker.exists()
    assert not orphan_root.exists()


async def test_task_workspace_first_marker_write_failure_removes_exclusive_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            workflow = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
    task_id = "t_01234567"

    def fail_first_write(path: Path, text: str) -> None:
        del path, text
        raise OSError("marker storage unavailable")

    monkeypatch.setattr(workspace_admission_module, "_write_new_text", fail_first_write)

    with pytest.raises(OSError, match="marker storage unavailable"):
        stage_task_workspace(
            workspace=workspace,
            task_id=task_id,
            workflow_revision=workflow,
            initial_team=plan_initial_task_team(workflow, task_id),
        )

    assert not (workspace / ".banksia" / task_id).exists()


async def test_task_start_retries_exclusive_workspace_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ids = iter(("t_01234567", "t_89abcdef"))

    async def allocate(*args: object, **kwargs: object) -> str:
        del args, kwargs
        return next(ids)

    real_stage = task_start_module.stage_task_workspace
    staged_ids: list[str] = []

    def collide_once(**kwargs: Any) -> Any:
        staged_ids.append(str(kwargs["task_id"]))
        if len(staged_ids) == 1:
            raise FileExistsError("simulated exclusive-create race")
        return real_stage(**kwargs)

    monkeypatch.setattr(task_start_module, "allocate_task_id", allocate)
    monkeypatch.setattr(task_start_module, "stage_task_workspace", collide_once)
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=_dependencies(
                    _CommittedRuntimePublisher(session),
                    workspace=workspace,
                ),
            )

    assert staged_ids == ["t_01234567", "t_89abcdef"]
    assert response.task_id == "t_89abcdef"
    assert (workspace / ".banksia" / response.task_id / "manifest.md").is_file()


async def test_task_start_marker_clear_failure_keeps_recovery_and_publishes_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail_accept(admission: object) -> None:
        del admission
        raise OSError("marker unlink unavailable")

    monkeypatch.setattr(task_start_module, "accept_task_workspace", fail_accept)
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            publisher = _CommittedRuntimePublisher(session)
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=_dependencies(publisher, workspace=workspace),
            )

            task = await session.get(TaskModel, response.task_id)

    assert task is not None
    assert (workspace / ".banksia" / response.task_id / TASK_INITIALIZATION_MARKER).is_file()
    assert len(publisher.signals) == 1
    assert isinstance(publisher.signals[0], DispatchStartDue)


async def test_task_start_persists_injected_runtime_budget_snapshot(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            publisher = _CommittedRuntimePublisher(session)
            dependencies = DispatchOpeningDependencies.create(
                settings=Settings(
                    controller_workspace=workspace,
                    runtime=RuntimeSettings(
                        default_provider=ProviderKind.CODEX,
                        max_child_assignments_per_assignment=7,
                        max_retries_per_assignment=3,
                        max_wave_members=4,
                    ),
                    codex=CodexSettings(enabled=True),
                ),
                available_adapter_kinds={ProviderKind.CODEX},
                post_commit_publisher=publisher,
            )
            response = await start_task(
                _request(workspace),
                session=session,
                dependencies=dependencies,
            )

            task = await session.get(TaskModel, response.task_id)
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == response.task_id)
            )

    assert task is not None
    assert task.max_child_assignments_per_assignment == 7
    assert task.max_retries_per_assignment == 3
    assert task.max_wave_members == 4
    assert assignment is not None
    assert assignment.child_assignment_limit == 7
    assert assignment.retry_limit == 3


async def _read_started_task_state(
    session: Any,
    *,
    task_id: str,
) -> _StartedTaskState:
    task = await session.get(TaskModel, task_id)
    assignment = await session.scalar(
        select(AssignmentModel).where(AssignmentModel.task_id == task_id)
    )
    file_rows = tuple(
        await session.scalars(
            select(AssignmentFileReferenceModel)
            .join(
                AssignmentModel,
                AssignmentModel.assignment_id == AssignmentFileReferenceModel.assignment_id,
            )
            .where(AssignmentModel.task_id == task_id)
            .order_by(AssignmentFileReferenceModel.order_index)
        )
    )
    attempt = await session.scalar(select(AttemptModel).where(AttemptModel.task_id == task_id))
    dispatch = await session.scalar(
        select(DispatchTurnModel).where(DispatchTurnModel.task_id == task_id)
    )
    prompt_refs = (
        await session.get(DispatchPromptRefsModel, dispatch.dispatch_id)
        if dispatch is not None
        else None
    )
    flow = await session.scalar(select(FlowModel).where(FlowModel.task_id == task_id))
    source = await session.scalar(
        select(FlowStartSourceModel).where(FlowStartSourceModel.task_id == task_id)
    )
    counts = (
        await _task_row_count(session, TeamRevisionModel, task_id),
        await _task_row_count(session, AssignmentModel, task_id),
        await _task_row_count(session, AttemptModel, task_id),
        await _task_row_count(session, FlowModel, task_id),
        await _flow_revision_count(session, task_id),
        await _task_row_count(session, FlowStartSourceModel, task_id),
        await _task_row_count(session, TaskEventModel, task_id),
    )
    return _StartedTaskState(
        task=task,
        assignment=assignment,
        file_rows=file_rows,
        attempt=attempt,
        dispatch=dispatch,
        prompt_refs=prompt_refs,
        flow=flow,
        source=source,
        counts=counts,
    )


def _assert_started_task_state(
    *,
    response: TaskStartResponse,
    started: _StartedTaskState,
    publisher: _CommittedRuntimePublisher,
    workspace: Path,
) -> None:
    assert response.status == "accepted"
    assert _TASK_ID_PATTERN.fullmatch(response.task_id)
    assert response.workflow == "reviewed-delivery"
    assert response.workflow_revision == 1
    assert response.workspace == workspace.resolve()
    assert response.manifest == Path(".banksia") / response.task_id / "manifest.md"
    assert started.task is not None and started.task.workflow_revision_no == 1
    assert started.task.current_team_revision_id is not None
    assert started.assignment is not None
    assert started.assignment.prompt == "Preserve  leading space.\nThen deliver.\n"
    assert [(row.path, row.description) for row in started.file_rows] == [
        ("brief.md", "Read this first."),
    ]
    assert started.attempt is not None and started.attempt.status == "running"
    assert started.dispatch is not None and started.dispatch.status == "starting"
    assert started.flow is not None
    assert started.flow.current_dispatch_id == started.dispatch.dispatch_id
    assert started.source is not None
    assert started.source.successor_dispatch_id == started.dispatch.dispatch_id
    assert started.prompt_refs is not None
    assert started.counts == (1, 1, 1, 1, 1, 1, 2)
    assert len(publisher.signals) == 1
    assert isinstance(publisher.signals[0], DispatchStartDue)
    assert publisher.signals[0].dispatch_id == started.dispatch.dispatch_id


def _assert_started_task_workspace(task_root: Path) -> None:
    manifest = task_root / "manifest.md"
    assert manifest.is_file()
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "# Banksia team" in manifest_text
    assert "Active revision" not in manifest_text
    assert "Member configuration" not in manifest_text
    assert "Branch basis" not in manifest_text
    assert (task_root / "workflow-note.md").is_file()
    assert (task_root / "notes").is_dir()
    assert (task_root / "artifacts").is_dir()
    assert (task_root / "command-runs").is_dir()
    assert not (task_root / TASK_INITIALIZATION_MARKER).exists()
    assert not tuple(task_root.glob("**/assignment.*"))


async def _task_count(session: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(TaskModel)) or 0)


async def _task_row_count(session: Any, model: Any, task_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.task_id == task_id)
        )
        or 0
    )


async def _flow_revision_count(session: Any, task_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(FlowRevisionModel)
            .join(FlowModel, FlowModel.flow_id == FlowRevisionModel.flow_id)
            .where(FlowModel.task_id == task_id)
        )
        or 0
    )


def _request(
    workspace: Path,
    *,
    workflow: str = "reviewed-delivery",
) -> TaskStartRequest:
    return TaskStartRequest(
        workflow=workflow,
        prompt="Complete the requested work.",
        workspace=workspace,
    )


def _dependencies(
    publisher: _CommittedRuntimePublisher,
    *,
    workspace: Path,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )

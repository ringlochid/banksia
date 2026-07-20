from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import autoclaw.runtime.launch.service as launch_service_module
import pytest
from autoclaw.persistence.models import TaskEventStreamHeadModel
from autoclaw.runtime import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
    RuntimeLaunchInput,
    TaskComposeInput,
)
from autoclaw.runtime.contracts import ResolvedNodeContext
from autoclaw.runtime.launch.bootstrap import (
    build_launch_bootstrap_persistence_context,
    build_launch_bootstrap_result,
    stage_launch_bootstrap_rows,
)
from autoclaw.runtime.launch.service import launch_task_runtime
from autoclaw.runtime.task_root import resolve_task_root_paths
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.workflow_compiler.support import (
    compile_packaged_workflow_fixture,
    compile_workflow_fixture,
    load_packaged_seed_lookup,
    load_packaged_workflow_fixture,
)


class _RecordingSession:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self, objects: tuple[object, ...] | None = None) -> None:
        del objects


async def test_launch_bootstrap_builds_controller_records_without_dispatch_or_files(
    tmp_path: Path,
) -> None:
    workflow = load_packaged_workflow_fixture("bounded_change")
    task_root = tmp_path / "task-root"
    bootstrap_input = RuntimeBootstrapInput(
        task_id="task.bootstrap",
        active_flow_revision_id="flowrev.bootstrap.1",
        attempt_id="attempt.bootstrap.root.1",
        assignment_key="task.bootstrap.root.assignment.1",
        task_root=task_root,
        task_compose=TaskComposeInput.model_validate(
            {
                "task": {
                    "key": "bootstrap",
                    "title": "Bootstrap task",
                    "summary": "Persist a runnable root source.",
                },
                "workflow": {"key": workflow.id},
            }
        ),
        workflow_definition=workflow,
        compiled_plan=compile_packaged_workflow_fixture("bounded_change", 1),
        role_policy_lookup=load_packaged_seed_lookup(),
    )
    result = build_launch_bootstrap_result(bootstrap_input)
    recording_session = _RecordingSession()
    await stage_launch_bootstrap_rows(
        cast(AsyncSession, recording_session),
        bootstrap_input=bootstrap_input,
        result=result,
        context=build_launch_bootstrap_persistence_context(bootstrap_input=bootstrap_input),
    )

    assert result.assignment.node_key == "root"
    assert result.assignment.assignment_key == "task.bootstrap.root.assignment.1"
    assert all(not ref.path.is_absolute() for ref in result.assignment.criteria)
    assert all(ref.path.parts[:2] == ("_runtime", "criteria") for ref in result.assignment.criteria)
    assert result.paths.task_root == task_root.resolve()
    assert not result.paths.task_root.exists()
    assert set(type(result).model_fields) == {"paths", "assignment"}
    event_stream_heads = [
        row for row in recording_session.rows if isinstance(row, TaskEventStreamHeadModel)
    ]
    assert [head.task_id for head in event_stream_heads] == [bootstrap_input.task_id]


async def test_launch_service_derives_initial_ids_from_nonliteral_root_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = load_packaged_workflow_fixture("bounded_change")
    workflow = baseline.model_copy(
        update={
            "root": baseline.root.model_copy(update={"node_key": "primary"}),
        }
    )
    compiled_plan = compile_workflow_fixture(workflow, revision_no=1)
    lookup = load_packaged_seed_lookup()
    captured_inputs: list[RuntimeBootstrapInput] = []

    async def compile_snapshot(
        session: AsyncSession,
        *,
        workflow_key: str,
        compiler_version: str,
    ) -> SimpleNamespace:
        del session
        assert workflow_key == workflow.id
        assert compiler_version == "runtime-launch"
        return SimpleNamespace(
            workflow=SimpleNamespace(definition=workflow),
            compiled_plan=compiled_plan,
            role_policy_lookup=lookup,
        )

    async def persist_bootstrap(
        session: AsyncSession,
        bootstrap_input: RuntimeBootstrapInput,
        *,
        should_commit: bool,
    ) -> RuntimeBootstrapResult:
        del session
        assert should_commit is False
        captured_inputs.append(bootstrap_input)
        return build_launch_bootstrap_result(bootstrap_input)

    monkeypatch.setattr(
        launch_service_module,
        "compile_current_workflow_launch_snapshot",
        compile_snapshot,
    )
    monkeypatch.setattr(
        launch_service_module,
        "persist_bootstrap_runtime_from_precomputed",
        persist_bootstrap,
    )
    launch_input = RuntimeLaunchInput(
        task_id="task.nonliteral-root",
        task_root=tmp_path / "task-root",
        task_compose=TaskComposeInput.model_validate(
            {
                "task": {
                    "key": "nonliteral-root",
                    "title": "Launch nonliteral root",
                    "summary": "Derive initial runtime identity from workflow truth.",
                },
                "workflow": {"key": workflow.id},
            }
        ),
    )

    result = await launch_task_runtime(cast(AsyncSession, object()), launch_input)

    assert result.bootstrap.assignment.node_key == "primary"
    assert len(captured_inputs) == 1
    assert captured_inputs[0].attempt_id == "attempt.task.nonliteral-root.primary.01"
    assert captured_inputs[0].assignment_key == "task.nonliteral-root.primary.assign-01"


def test_task_compose_rejects_removed_context_root_binding() -> None:
    with pytest.raises(ValidationError, match="context"):
        TaskComposeInput.model_validate(
            {
                "task": {
                    "key": "bootstrap",
                    "title": "Bootstrap task",
                    "summary": "Reject removed roots.",
                },
                "workflow": {"key": "bounded-change"},
                "roots": {
                    "context": {
                        "mode": "use_existing_host",
                        "host_path": "/tmp/legacy-context",
                    }
                },
            }
        )


def test_resolved_node_context_requires_pinned_policy() -> None:
    payload = {
        "node_key": "root",
        "node_kind": "root",
        "node_description": "Coordinate the root assignment.",
        "role_key": "planning-lead",
        "role_revision_no": 1,
        "role_description": "Coordinate bounded work.",
    }

    with pytest.raises(ValidationError, match="policy_key"):
        ResolvedNodeContext.model_validate(payload)


@pytest.mark.parametrize("mode", ["ensure_host_path", "use_existing_host"])
def test_workspace_host_binding_rejects_existing_file(tmp_path: Path, mode: str) -> None:
    workspace_file = tmp_path / "not-a-workspace"
    workspace_file.write_text("not a directory", encoding="utf-8")
    task_compose = TaskComposeInput.model_validate(
        {
            "task": {
                "key": "bootstrap",
                "title": "Bootstrap task",
                "summary": "Reject a non-directory workspace root.",
            },
            "workflow": {"key": "bounded-change"},
            "roots": {
                "workspace": {
                    "mode": mode,
                    "host_path": workspace_file,
                }
            },
        }
    )

    with pytest.raises(NotADirectoryError, match="workspace host path is not a directory"):
        resolve_task_root_paths(
            task_root=tmp_path / "task-root",
            task_compose=task_compose,
        )

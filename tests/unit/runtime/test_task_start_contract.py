from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from banksia.interfaces.http.router import api_router
from banksia.runtime.contracts import (
    AssignmentBody,
    CheckpointRequest,
    FileReference,
    HumanRequestItem,
    HumanRequestKind,
    HumanRequestOpenRequest,
    TaskStartRequest,
)
from banksia.runtime.workspace.admission import TaskWorkspaceAdmissionCoordinator


def test_task_start_has_one_strict_transient_contract() -> None:
    schema = TaskStartRequest.model_json_schema()

    assert tuple(schema["properties"]) == ("workflow", "prompt", "workspace", "files")
    assert set(schema["required"]) == {"workflow", "prompt"}
    assert "taskcompose" not in str(schema).casefold()
    for removed in ("task", "task_key", "title", "summary", "instruction"):
        assert removed not in schema["properties"]

    with pytest.raises(ValidationError):
        TaskStartRequest.model_validate(
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "title": "Deleted Task prose",
            }
        )


def test_task_and_assignment_prompts_preserve_exact_text_after_newline_normalization() -> None:
    request = TaskStartRequest(
        workflow="reviewed-delivery",
        prompt="  First.\r\nSecond.\r  ",
    )

    assert request.prompt == "  First.\nSecond.\n  "

    assignment = AssignmentBody(
        prompt=request.prompt,
        files=(FileReference(path="./brief.md", description="  useful  "),),
    )
    assert assignment.prompt == request.prompt
    assert assignment.files[0].path == "brief.md"
    assert assignment.files[0].description == "  useful  "


def test_task_start_rejects_blank_illegal_oversized_and_duplicate_values() -> None:
    for prompt in (" \r\n ", "bad\x00text", "bad\ud800text", "x" * (64 * 1024 + 1)):
        with pytest.raises((ValidationError, ValueError)):
            TaskStartRequest(workflow="reviewed-delivery", prompt=prompt)

    with pytest.raises((ValidationError, ValueError)):
        TaskStartRequest(
            workflow="reviewed-delivery",
            prompt="Do the work.",
            files=(
                FileReference(path="./brief.md"),
                FileReference(path="brief.md"),
            ),
        )


def test_file_reference_limit_is_hidden_but_controller_enforced() -> None:
    request_schema = TaskStartRequest.model_json_schema()
    assignment_schema = AssignmentBody.model_json_schema()
    checkpoint_schema = CheckpointRequest.model_json_schema()
    human_request_schema = HumanRequestOpenRequest.model_json_schema()

    assert "maxItems" not in str(request_schema)
    assert "maxItems" not in str(assignment_schema)
    assert checkpoint_schema["properties"]["files"].get("maxItems") is None
    assert human_request_schema["properties"]["files"].get("maxItems") is None
    files = tuple(FileReference(path=f"input-{index}.md") for index in range(33))
    with pytest.raises(ValidationError, match="controller entry limit"):
        TaskStartRequest(
            workflow="reviewed-delivery",
            prompt="Do the work.",
            files=files,
        )
    with pytest.raises(ValidationError, match="controller entry limit"):
        AssignmentBody(prompt="Do the work.", files=files)
    with pytest.raises(ValidationError, match="controller entry limit"):
        CheckpointRequest(summary="Work complete.", files=files)
    with pytest.raises(ValidationError, match="controller entry limit"):
        HumanRequestOpenRequest(
            kind=HumanRequestKind.INPUT,
            summary="A decision is required.",
            items=(
                HumanRequestItem(
                    id="decision",
                    prompt="What should the team do?",
                    response_schema={"type": "string"},
                ),
            ),
            files=files,
        )


def test_file_reference_is_only_normalized_path_and_optional_description() -> None:
    schema = FileReference.model_json_schema()
    assert tuple(schema["properties"]) == ("path", "description")

    for path in (
        "",
        "/absolute.md",
        "../escape.md",
        "nested/../escape.md",
        "C:/drive.md",
        "https://example.test/file",
        "glob/*.md",
        "windows\\path.md",
        "illegal-\x01.md",
    ):
        with pytest.raises((ValidationError, ValueError)):
            FileReference(path=path)


def test_task_start_http_contract_has_no_compose_or_preview_route() -> None:
    app = FastAPI()
    app.include_router(api_router)
    openapi = app.openapi()

    assert "/tasks" in openapi["paths"]
    assert "TaskStartRequest" in openapi["components"]["schemas"]
    assert "TaskStartReceipt" in openapi["components"]["schemas"]
    serialized = str(openapi).casefold()
    assert "task-compose" not in serialized
    assert "taskcompose" not in serialized


async def test_workspace_admission_coordinator_serializes_only_the_same_workspace(
    tmp_path: Path,
) -> None:
    coordinator = TaskWorkspaceAdmissionCoordinator()
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    same_workspace_entered = asyncio.Event()
    other_workspace_entered = asyncio.Event()

    async def enter(workspace: Path, entered: asyncio.Event) -> None:
        async with coordinator.hold(workspace):
            entered.set()

    async with coordinator.hold(first_workspace):
        same_workspace = asyncio.create_task(enter(first_workspace, same_workspace_entered))
        other_workspace = asyncio.create_task(enter(second_workspace, other_workspace_entered))
        await asyncio.wait_for(other_workspace_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not same_workspace_entered.is_set()

    await asyncio.wait_for(same_workspace_entered.wait(), timeout=1)
    await asyncio.gather(same_workspace, other_workspace)

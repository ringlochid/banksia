from __future__ import annotations

import asyncio
import os
import secrets
import shlex
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    CommandRunModel,
    FlowWaitModel,
    HumanRequestFileReferenceModel,
    HumanRequestModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run.task_paths import normalize_command_working_directory
from banksia.runtime.contracts import (
    CommandRunStartResponse,
    CommandRunState,
    FileReference,
    HumanRequestOpenResponse,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.file_references import validate_file_references
from banksia.runtime.node_operations.contracts import (
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from banksia.runtime.node_operations.source_transitions import close_source_dispatch
from banksia.runtime.task_events import append_task_event
from banksia.runtime.task_root.paths import command_run_output_path
from banksia.runtime.task_root.reads import read_task_root_paths

COMMAND_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


async def open_human_request(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: OpenHumanRequestRequest,
) -> HumanRequestOpenResponse:
    request_id = f"human-request.{authority.task_id}.{uuid4().hex}"
    body = request.request
    paths = await read_task_root_paths(session, authority.task_id)
    files = validate_file_references(paths.workspace_path, body.files)
    now = utc_now()
    await close_source_dispatch(
        session,
        authority,
        now=now,
        closed_reason="human_request_wait",
        waiting_cause="human_request",
        waiting_source_id=request_id,
    )
    session.add(
        HumanRequestModel(
            request_id=request_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            request_kind=body.kind.value,
            request_summary=body.summary,
            request_items_json=[item.model_dump(mode="json") for item in body.items],
            capability_basis_json={"decision": "allow", "kind": body.kind.value},
            due_at=body.timeout.due_at,
            timeout_policy_json=({"kind": "deadline"} if body.timeout.due_at is not None else None),
            default_behavior_json=(
                {"value": body.timeout.default_behavior}
                if body.timeout.default_behavior is not None
                else None
            ),
            status="open",
        )
    )
    _stage_human_request_files(session, request_id=request_id, files=files)
    session.add(
        FlowWaitModel(
            flow_id=authority.flow_id,
            task_id=authority.task_id,
            source_dispatch_id=authority.dispatch_id,
            human_request_id=request_id,
            command_run_id=None,
        )
    )
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_OPENED,
        event_source=TaskEventSource.NODE,
        occurred_at=now,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "request_id": request_id,
            "kind": body.kind.value,
            "summary": body.summary,
            "source_dispatch_id": authority.dispatch_id,
            "due_at": body.timeout.due_at,
            "opened_at": now,
        },
    )
    await session.commit()
    return HumanRequestOpenResponse(request_id=request_id, task_id=authority.task_id)


async def start_command_run(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: StartCommandRunRequest,
) -> CommandRunStartResponse:
    paths = await read_task_root_paths(session, authority.task_id)
    run_id = await _allocate_command_run_id(
        session,
        task_id=authority.task_id,
        workspace=paths.workspace_path,
    )
    output_path = command_run_output_path(
        task_id=authority.task_id,
        run_id=run_id,
    ).as_posix()
    body = request.request
    now = utc_now()
    cwd = _normalize_command_cwd(body.cwd)
    await close_source_dispatch(
        session,
        authority,
        now=now,
        closed_reason="command_run_wait",
        waiting_cause="command_run",
        waiting_source_id=run_id,
    )
    _stage_command_run_rows(
        session,
        authority,
        run_id=run_id,
        request=request,
        cwd=cwd,
        output_path=output_path,
    )
    await _append_command_run_opened_event(
        session,
        authority,
        run_id=run_id,
        request=request,
        cwd=cwd,
        output_path=output_path,
        occurred_at=now,
    )
    await session.commit()
    return CommandRunStartResponse(
        run_id=run_id,
        task_id=authority.task_id,
        state=CommandRunState.PENDING_START,
        output_path=output_path,
    )


def _stage_human_request_files(
    session: AsyncSession,
    *,
    request_id: str,
    files: tuple[FileReference, ...],
) -> None:
    session.add_all(
        HumanRequestFileReferenceModel(
            request_id=request_id,
            order_index=index,
            path=file.path,
            description=file.description,
        )
        for index, file in enumerate(files)
    )


def _stage_command_run_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    run_id: str,
    request: StartCommandRunRequest,
    cwd: str | None,
    output_path: str,
) -> None:
    body = request.request
    session.add(
        CommandRunModel(
            run_id=run_id,
            task_id=authority.task_id,
            flow_id=authority.flow_id,
            assignment_id=authority.assignment_id,
            attempt_id=authority.attempt_id,
            source_dispatch_id=authority.dispatch_id,
            command_spec_json=body.command.model_dump(mode="json"),
            cwd_policy_json={"logical_path": cwd} if cwd is not None else None,
            summary=body.summary,
            timeout_seconds=body.timeout_seconds,
            due_at=None,
            output_path=output_path,
            state=CommandRunState.PENDING_START,
            ownership_revision=0,
        )
    )
    session.add(
        FlowWaitModel(
            flow_id=authority.flow_id,
            task_id=authority.task_id,
            source_dispatch_id=authority.dispatch_id,
            human_request_id=None,
            command_run_id=run_id,
        )
    )


async def _append_command_run_opened_event(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    run_id: str,
    request: StartCommandRunRequest,
    cwd: str | None,
    output_path: str,
    occurred_at: datetime,
) -> None:
    body = request.request
    command = shlex.join(body.command.argv) if body.command.kind == "argv" else body.command.command
    await append_task_event(
        session,
        task_id=authority.task_id,
        event_type=TaskEventType.COMMAND_RUN_OPENED,
        event_source=TaskEventSource.NODE,
        occurred_at=occurred_at,
        flow_revision_id=authority.flow_revision_id,
        dispatch_id=authority.dispatch_id,
        attempt_id=authority.attempt_id,
        node_key=authority.node_key,
        payload={
            "run_id": run_id,
            "source_dispatch_id": authority.dispatch_id,
            "state": CommandRunState.PENDING_START.value,
            "command": command,
            "description": body.summary,
            "workdir": cwd,
            "created_at": occurred_at,
            "timeout_seconds": body.timeout_seconds,
            "ownership_revision": 0,
            "output_path": output_path,
        },
    )


def _normalize_command_cwd(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    try:
        return normalize_command_working_directory(cwd)
    except ValueError as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.INVALID_TASK_PATH,
            summary=str(exc),
            is_retryable=False,
        ) from exc


async def _allocate_command_run_id(
    session: AsyncSession,
    *,
    task_id: str,
    workspace: Path,
) -> str:
    for _ in range(128):
        candidate = _new_command_run_id()
        if await session.get(CommandRunModel, candidate) is not None:
            continue
        directory = workspace / command_run_output_path(task_id=task_id, run_id=candidate).parent
        if not await asyncio.to_thread(os.path.lexists, directory):
            return candidate
    raise RuntimeError("could not allocate a collision-free Command identifier")


def _new_command_run_id() -> str:
    value = int.from_bytes(secrets.token_bytes(5), "big")
    encoded = "".join(COMMAND_ID_ALPHABET[(value >> shift) & 0x1F] for shift in range(35, -1, -5))
    return f"c_{encoded}"


__all__ = ["open_human_request", "start_command_run"]

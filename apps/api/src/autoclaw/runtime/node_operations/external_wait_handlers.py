from __future__ import annotations

import shlex
from datetime import datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import CommandRunModel, FlowWaitModel, HumanRequestModel
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import (
    CommandExpectedOutput,
    CommandRunStartResponse,
    CommandRunState,
    HumanRequestOpenResponse,
    TaskEventSource,
    TaskEventType,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import NodeOperationAuthority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.contracts import (
    OpenHumanRequestRequest,
    StartCommandRunRequest,
)
from autoclaw.runtime.node_operations.source_transitions import close_source_dispatch
from autoclaw.runtime.task_events import append_task_event
from autoclaw.runtime.task_root.logical_paths import normalize_logical_task_path


async def open_human_request(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: OpenHumanRequestRequest,
) -> HumanRequestOpenResponse:
    request_id = f"human-request.{authority.task_id}.{uuid4().hex}"
    body = request.request
    context_refs = [
        {
            "path": normalize_logical_task_path(context_ref.path),
            "description": context_ref.description,
        }
        for context_ref in body.context_refs
    ]
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
            context_refs_json=context_refs or None,
            suggested_human_instruction=body.suggested_human_instruction,
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
    run_id = f"command-run.{authority.task_id}.{uuid4().hex}"
    body = request.request
    now = utc_now()
    cwd = _normalize_command_cwd(body.cwd)
    expected_outputs = _normalize_expected_outputs(body.expected_outputs)
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
        expected_outputs=expected_outputs,
    )
    await _append_command_run_opened_event(
        session,
        authority,
        run_id=run_id,
        request=request,
        cwd=cwd,
        occurred_at=now,
    )
    await session.commit()
    return CommandRunStartResponse(
        run_id=run_id,
        task_id=authority.task_id,
        state=CommandRunState.PENDING_START,
    )


def _normalize_expected_outputs(
    expected_outputs: tuple[CommandExpectedOutput, ...],
) -> list[dict[str, str]]:
    return [
        {
            "path": normalize_logical_task_path(output.path),
            "description": output.description,
        }
        for output in expected_outputs
    ]


def _stage_command_run_rows(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    *,
    run_id: str,
    request: StartCommandRunRequest,
    cwd: str | None,
    expected_outputs: list[dict[str, str]],
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
            environment_refs_json=list(body.environment) or None,
            summary=body.summary,
            expected_outputs_json=expected_outputs or None,
            timeout_seconds=body.timeout_seconds,
            due_at=None,
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
        },
    )


def _normalize_command_cwd(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    normalized = normalize_logical_task_path(cwd)
    if normalized != "workspace" and not normalized.startswith("workspace/"):
        raise RuntimeOperationError(
            code=OperationFailureCode.INVALID_TASK_PATH,
            summary="command cwd must be inside the task workspace",
            is_retryable=False,
        )
    return normalized


__all__ = ["open_human_request", "start_command_run"]

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import cast

import autoclaw.interfaces.mcp.operator.definition_tools as definition_tools_module
import autoclaw.interfaces.mcp.operator.runtime_tools as runtime_tools_module
import pytest
from autoclaw.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from autoclaw.runtime.contracts import (
    FlowStatus,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestResolveResponse,
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    RuntimeLifecycleStatus,
    TaskStartRequest,
    TaskStartResponse,
    WorkflowManifestRef,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.post_commit import CapturedRuntimeEffectPublisher
from autoclaw.runtime.projection import SupportProjectionSignal
from sqlalchemy.ext.asyncio import AsyncSession


class _ProjectionPublisher:
    def publish(self, signal: SupportProjectionSignal) -> bool:
        del signal
        return True


@asynccontextmanager
async def _session_context() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


async def _capture_start_task(
    captured: dict[str, object],
    request: TaskStartRequest,
    *,
    data_dir: Path | None = None,
    session: AsyncSession | None = None,
    runtime_effect_publisher: object = None,
    support_projection_publisher: object = None,
) -> TaskStartResponse:
    del request, data_dir, session
    captured["start_runtime"] = runtime_effect_publisher
    captured["start_projection"] = support_projection_publisher
    return TaskStartResponse(
        task_id="task.operator-injection",
        compiled_plan_id="compiled-plan.task.operator-injection",
        active_flow_revision_id="flow-revision.operator-injection.1",
        flow_status=FlowStatus.RUNNING,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description="Committed workflow manifest support projection.",
        ),
    )


async def _capture_human_resolution(
    captured: dict[str, object],
    session: AsyncSession,
    *,
    task_id: str,
    request_id: str,
    request: object,
    actor_ref: str | None = None,
    resolved_by_surface: object = None,
    runtime_effect_publisher: object = None,
) -> HumanRequestResolveResponse:
    del session, request
    captured["resolve_runtime"] = runtime_effect_publisher
    captured["resolve_actor_ref"] = actor_ref
    captured["resolve_surface"] = resolved_by_surface
    return HumanRequestResolveResponse(
        task_id=task_id,
        resolution=HumanRequestResolution(
            request_id=request_id,
            task_id=task_id,
            resolution_kind=HumanRequestResolutionKind.ANSWERED,
            item_responses={"direction": "a"},
            policy_basis={"policy_basis": "test"},
            summary="Human answered the controller-owned request.",
            resolved_at=datetime.now(UTC),
            resolved_by_surface=HumanRequestResolutionSurface.OPERATOR_MCP,
        ),
    )


def _task_start_request() -> TaskStartRequest:
    return TaskStartRequest.model_validate(
        {
            "task": {
                "key": "operator-publisher-injection",
                "title": "Operator publisher injection",
                "summary": "Keep operator source effects explicit.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )


async def _capture_pause_flow(
    captured: dict[str, object],
    session: AsyncSession,
    task_id: str,
    **kwargs: object,
) -> RuntimeFlowPauseResponse:
    del session
    captured["pause"] = kwargs
    return RuntimeFlowPauseResponse(flow=_runtime_flow_read(task_id, control_revision=8))


async def _capture_continue_flow(
    captured: dict[str, object],
    session: AsyncSession,
    task_id: str,
    **kwargs: object,
) -> RuntimeFlowRead:
    del session
    captured["continue"] = kwargs
    return _runtime_flow_read(task_id, control_revision=8)


async def _capture_cancel_flow(
    captured: dict[str, object],
    session: AsyncSession,
    task_id: str,
    **kwargs: object,
) -> RuntimeFlowRead:
    del session
    captured["cancel"] = kwargs
    return _runtime_flow_read(task_id, control_revision=8)


def _install_effect_capture_patches(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, object],
) -> None:
    monkeypatch.setattr(
        definition_tools_module,
        "task_start_request_from_path",
        lambda path: _task_start_request(),
    )
    monkeypatch.setattr(
        definition_tools_module,
        "start_task_from_definition",
        partial(_capture_start_task, captured),
    )
    monkeypatch.setattr(runtime_tools_module, "get_session_factory", lambda: _session_context)
    monkeypatch.setattr(
        runtime_tools_module,
        "resolve_human_request",
        partial(_capture_human_resolution, captured),
    )
    monkeypatch.setattr(
        runtime_tools_module,
        "pause_runtime_flow",
        partial(_capture_pause_flow, captured),
    )
    monkeypatch.setattr(
        runtime_tools_module,
        "continue_runtime_flow",
        partial(_capture_continue_flow, captured),
    )
    monkeypatch.setattr(
        runtime_tools_module,
        "cancel_runtime_flow",
        partial(_capture_cancel_flow, captured),
    )


async def test_operator_tools_receive_the_server_owned_effect_publishers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_publisher = CapturedRuntimeEffectPublisher()
    projection_publisher = _ProjectionPublisher()
    opening_dependencies = cast(DispatchOpeningDependencies, object())
    captured: dict[str, object] = {}
    _install_effect_capture_patches(monkeypatch, captured)
    server = create_operator_mcp_server(
        effect_publishers=OperatorEffectPublishers(
            runtime_effect_publisher=runtime_publisher,
            support_projection_publisher=projection_publisher,
            dispatch_opening_dependencies=opening_dependencies,
        )
    )

    await server.call_tool(
        "start_task",
        {"task_compose_path": "/tmp/operator-publisher-injection.yaml"},
    )
    await server.call_tool(
        "resolve_human_request",
        {
            "task_id": "task.operator-injection",
            "request_id": "request.operator-injection",
            "item_responses": {"direction": "a"},
        },
    )
    control_arguments = {
        "task_id": "task.operator-injection",
        "expected_active_flow_revision_id": "flow-revision.operator-injection.1",
        "expected_control_revision": 7,
    }
    for tool_name in ("pause_task", "continue_task", "cancel_task"):
        await server.call_tool(tool_name, control_arguments)

    assert captured == {
        "start_runtime": runtime_publisher,
        "start_projection": projection_publisher,
        "resolve_runtime": runtime_publisher,
        "resolve_actor_ref": "local_operator",
        "resolve_surface": HumanRequestResolutionSurface.OPERATOR_MCP,
        "pause": {
            "expected_active_flow_revision_id": "flow-revision.operator-injection.1",
            "expected_control_revision": 7,
            "actor_ref": "local_operator",
            "event_source": runtime_tools_module.TaskEventSource.OPERATOR_MCP,
            "runtime_effect_publisher": runtime_publisher,
        },
        "continue": {
            "expected_active_flow_revision_id": "flow-revision.operator-injection.1",
            "expected_control_revision": 7,
            "dependencies": opening_dependencies,
            "actor_ref": "local_operator",
            "event_source": runtime_tools_module.TaskEventSource.OPERATOR_MCP,
        },
        "cancel": {
            "expected_active_flow_revision_id": "flow-revision.operator-injection.1",
            "expected_control_revision": 7,
            "actor_ref": "local_operator",
            "event_source": runtime_tools_module.TaskEventSource.OPERATOR_MCP,
            "runtime_effect_publisher": runtime_publisher,
        },
    }


def _runtime_flow_read(task_id: str, *, control_revision: int) -> RuntimeFlowRead:
    return RuntimeFlowRead(
        task_id=task_id,
        task_title="Operator publisher injection",
        task_summary="Keep operator flow-control ownership explicit.",
        status=RuntimeLifecycleStatus.RUNNING,
        active_flow_revision_id="flow-revision.operator-injection.1",
        control_revision=control_revision,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description="Committed workflow manifest support projection.",
        ),
        updated_at=datetime.now(UTC),
    )

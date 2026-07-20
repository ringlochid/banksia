from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue

from autoclaw.persistence.session import get_session_factory
from autoclaw.persistence.session_operations import read_session_operation
from autoclaw.runtime.command_run.service import (
    cancel_command_run,
    list_command_runs,
    read_command_run,
    read_command_run_log,
)
from autoclaw.runtime.contracts import (
    CommandRunCancelResponse,
    CommandRunListResponse,
    CommandRunLogReadResponse,
    CommandRunRecord,
    HumanRequestListResponse,
    HumanRequestResolutionSurface,
    HumanRequestResolveRequest,
    HumanRequestResolveResponse,
    OperatorFlowSnapshotResponse,
    OperatorFlowTraceQuery,
    OperatorFlowTraceResponse,
    RuntimeFlowControlRequest,
    RuntimeFlowPauseResponse,
    RuntimeFlowRead,
    RuntimeFlowSummaryListResponse,
    RuntimeTaskListQuery,
    TaskEventListResponse,
    TaskEventSource,
)
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.flow import (
    cancel_runtime_flow,
    continue_runtime_flow,
    list_runtime_flows,
    pause_runtime_flow,
    runtime_flow_read,
)
from autoclaw.runtime.human_request.service import list_human_requests, resolve_human_request
from autoclaw.runtime.observability import operator_snapshot, operator_trace
from autoclaw.runtime.post_commit import RuntimeEffectPublisher
from autoclaw.runtime.task_events import list_task_events

from ..tool_teaching import (
    FRESH_REVISION_NOTE,
    INSPECT_FIRST_NOTE,
    RUNTIME_STATE_WARNING,
    STATUS_CHECK_WARNING,
    mutating_tool_teaching,
    read_only_tool_teaching,
)

_OPERATOR_MCP_ACTOR_REF = "local_operator"

LIST_RUNTIME_TASKS_TEACHING = read_only_tool_teaching(
    name="list_runtime_tasks",
    summary="List task runtime summaries so you can find a task before deeper inspection.",
    details=(
        "Use get_runtime_task next for one task's current status and fresh revision.",
        "Inspect before mutating runtime state.",
    ),
)
GET_RUNTIME_TASK_TEACHING = read_only_tool_teaching(
    name="get_runtime_task",
    summary="Inspect current task status and control guards for one task.",
    details=(
        "Use this first for status checks and before pause_task, continue_task, or cancel_task.",
        "Use its active_flow_revision_id and control_revision as the fresh expected values "
        "for pause_task, continue_task, or cancel_task.",
    ),
)
GET_OPERATOR_SNAPSHOT_TEACHING = read_only_tool_teaching(
    name="get_operator_snapshot",
    summary="Inspect the current operator-facing state and current_paths for one task.",
    details=(
        "Use this after get_runtime_task when you need current state, not chronology.",
        "Observe before mutating runtime state.",
    ),
)
GET_OPERATOR_TRACE_TEACHING = read_only_tool_teaching(
    name="get_operator_trace",
    summary="Inspect dispatch and checkpoint chronology for one task.",
    details=(
        "Use this after get_runtime_task or get_operator_snapshot when you "
        "need to understand how the workflow reached the current state.",
        "Observe before mutating runtime state.",
    ),
)
GET_TASK_EVENTS_TEACHING = read_only_tool_teaching(
    name="get_task_events",
    summary="Backfill bounded controller chronology for one task.",
    details=(
        "Read get_runtime_task or get_operator_snapshot first because source rows "
        "own current truth.",
        "The cursor is exclusive and task-bound; through_event_id freezes a bounded page horizon.",
        "Events are chronology only. On cursor_reset_required, reread current state and restart.",
    ),
)
PAUSE_TASK_TEACHING = mutating_tool_teaching(
    name="pause_task",
    summary="Pause a task when you intentionally want to stop forward progress.",
    details=(
        RUNTIME_STATE_WARNING,
        FRESH_REVISION_NOTE,
        "The response means the pause and any current-dispatch closure committed.",
        "Provider cleanup is asynchronous; this tool does not wait for provider stop or exit.",
    ),
)
CONTINUE_TASK_TEACHING = mutating_tool_teaching(
    name="continue_task",
    summary="Resume a paused task after inspection confirms it should continue.",
    details=(
        RUNTIME_STATE_WARNING,
        STATUS_CHECK_WARNING,
        INSPECT_FIRST_NOTE,
        "Pause-resume only.",
        "Not the ordinary path for yielded child handoff, parent wake, or retry advancement.",
        FRESH_REVISION_NOTE,
        "The response means the legal successor dispatch and its request refs committed.",
        "Provider start is asynchronous; this tool does not wait for provider output, stop, or "
        "completion.",
    ),
)
CANCEL_TASK_TEACHING = mutating_tool_teaching(
    name="cancel_task",
    summary="Cancel a task when you intentionally want to stop it.",
    details=(
        RUNTIME_STATE_WARNING,
        FRESH_REVISION_NOTE,
        "The response means controller cancellation and any current-dispatch closure committed.",
        "Provider and command cleanup are asynchronous; this tool does not wait for process exit.",
    ),
)
GET_HUMAN_REQUESTS_TEACHING = read_only_tool_teaching(
    name="get_human_requests",
    summary="Inspect the current and historical human requests for one task.",
    details=(
        "Use this when a task is waiting for human input or when you need the "
        "resolved request history.",
        "Observe before submitting a resolution.",
    ),
)
RESOLVE_HUMAN_REQUEST_TEACHING = mutating_tool_teaching(
    name="resolve_human_request",
    summary="Submit one answered human-request resolution for the current open request.",
    details=(
        RUNTIME_STATE_WARNING,
        INSPECT_FIRST_NOTE,
        "Dedicated human-request control surface; do not substitute continue_task.",
        "Only the current open request for the task is legal.",
        "The response means the request resolution committed.",
        "Successor opening and provider start are independent asynchronous effects; this tool "
        "waits for neither.",
    ),
)
GET_COMMAND_RUNS_TEACHING = read_only_tool_teaching(
    name="get_command_runs",
    summary="Inspect controller-owned command-run summaries for one task.",
    details=(
        "Use this to find the current run id and state before deeper inspection or cancellation.",
        "Observe before mutating command-run state.",
    ),
)
GET_COMMAND_RUN_TEACHING = read_only_tool_teaching(
    name="get_command_run",
    summary="Inspect one controller-owned command-run record.",
    details=(
        "Use this when you need per-run timestamps, latest update, or terminal result detail.",
        "Read the log separately only when the run already exposes a log_ref.",
    ),
)
GET_COMMAND_RUN_LOG_TEACHING = read_only_tool_teaching(
    name="get_command_run_log",
    summary="Read the current or terminal command-run log text when one exists.",
    details=(
        "Use this only after get_command_runs or get_command_run confirms a log_ref is available.",
        "Logs are bounded controller-backed readback, not a second state source.",
    ),
)
CANCEL_COMMAND_RUN_TEACHING = mutating_tool_teaching(
    name="cancel_command_run",
    summary="Request cancellation of one active command run without cancelling the whole task.",
    details=(
        RUNTIME_STATE_WARNING,
        INSPECT_FIRST_NOTE,
        "Dedicated command-run control surface; do not substitute cancel_task "
        "unless you intend to stop the whole task.",
        "The response means cancellation_requested committed for the exact current run.",
        "It does not mean the process exited, the run became terminal, or a successor opened.",
    ),
)


def register_runtime_task_tools(server: FastMCP) -> None:
    @server.tool(
        name="list_runtime_tasks",
        title=LIST_RUNTIME_TASKS_TEACHING.title,
        description=LIST_RUNTIME_TASKS_TEACHING.description,
        annotations=LIST_RUNTIME_TASKS_TEACHING.annotations,
    )
    async def list_runtime_tasks(
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        sort: Literal[
            "updated_at_desc",
            "updated_at_asc",
            "task_title_asc",
            "task_title_desc",
        ] = "updated_at_desc",
        status: Literal[
            "any",
            "pending",
            "running",
            "paused",
            "completed",
            "cancelled",
        ] = "any",
    ) -> RuntimeFlowSummaryListResponse:
        filters = RuntimeTaskListQuery(
            q=query,
            limit=limit,
            cursor=cursor,
            sort=sort,
            status=status,
        )
        return await read_session_operation(
            lambda session: list_runtime_flows(
                session,
                q=filters.q,
                limit=filters.limit,
                cursor=filters.cursor,
                sort=filters.sort,
                status=filters.status,
            )
        )

    @server.tool(
        name="get_runtime_task",
        title=GET_RUNTIME_TASK_TEACHING.title,
        description=GET_RUNTIME_TASK_TEACHING.description,
        annotations=GET_RUNTIME_TASK_TEACHING.annotations,
    )
    async def get_runtime_task(task_id: str) -> RuntimeFlowRead:
        return await read_session_operation(lambda session: runtime_flow_read(session, task_id))


def register_operator_read_tools(server: FastMCP) -> None:
    @server.tool(
        name="get_operator_snapshot",
        title=GET_OPERATOR_SNAPSHOT_TEACHING.title,
        description=GET_OPERATOR_SNAPSHOT_TEACHING.description,
        annotations=GET_OPERATOR_SNAPSHOT_TEACHING.annotations,
    )
    async def get_operator_snapshot(task_id: str) -> OperatorFlowSnapshotResponse:
        return await read_session_operation(lambda session: operator_snapshot(session, task_id))

    @server.tool(
        name="get_operator_trace",
        title=GET_OPERATOR_TRACE_TEACHING.title,
        description=GET_OPERATOR_TRACE_TEACHING.description,
        annotations=GET_OPERATOR_TRACE_TEACHING.annotations,
    )
    async def get_operator_trace(
        task_id: str,
        scope: Literal["current", "whole"] = "current",
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        sort: Literal["occurred_at_desc", "occurred_at_asc"] = "occurred_at_desc",
    ) -> OperatorFlowTraceResponse:
        trace_query = OperatorFlowTraceQuery(
            scope=scope,
            q=query,
            limit=limit,
            cursor=cursor,
            sort=sort,
        )
        return await read_session_operation(
            lambda session: operator_trace(
                session,
                task_id,
                scope=trace_query.scope,
                q=trace_query.q,
                limit=trace_query.limit,
                cursor=trace_query.cursor,
                sort=trace_query.sort,
            )
        )

    @server.tool(
        name="get_task_events",
        title=GET_TASK_EVENTS_TEACHING.title,
        description=GET_TASK_EVENTS_TEACHING.description,
        annotations=GET_TASK_EVENTS_TEACHING.annotations,
    )
    async def get_task_events(
        task_id: str,
        cursor: str | None = None,
        limit: int = 100,
        through_event_id: str | None = None,
    ) -> TaskEventListResponse:
        return await read_session_operation(
            lambda session: list_task_events(
                session,
                task_id=task_id,
                cursor=cursor,
                limit=limit,
                through_event_id=through_event_id,
            )
        )


def register_runtime_control_tools(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    dependencies: DispatchOpeningDependencies | None = None,
) -> None:
    _register_pause_task_tool(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    _register_continue_task_tool(server, dependencies=dependencies)
    _register_cancel_task_tool(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )


def register_runtime_wait_tools(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> None:
    register_human_request_tools(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )
    register_command_run_tools(
        server,
        runtime_effect_publisher=runtime_effect_publisher,
    )


def require_dispatch_opening_dependencies(
    dependencies: DispatchOpeningDependencies | None,
) -> DispatchOpeningDependencies:
    if dependencies is None:
        raise RuntimeError("dispatch opening dependencies are unavailable")
    return dependencies


def register_human_request_tools(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> None:
    @server.tool(
        name="get_human_requests",
        title=GET_HUMAN_REQUESTS_TEACHING.title,
        description=GET_HUMAN_REQUESTS_TEACHING.description,
        annotations=GET_HUMAN_REQUESTS_TEACHING.annotations,
    )
    async def get_human_requests(task_id: str) -> HumanRequestListResponse:
        return await read_session_operation(
            lambda session: list_human_requests(session, task_id=task_id)
        )

    @server.tool(
        name="resolve_human_request",
        title=RESOLVE_HUMAN_REQUEST_TEACHING.title,
        description=RESOLVE_HUMAN_REQUEST_TEACHING.description,
        annotations=RESOLVE_HUMAN_REQUEST_TEACHING.annotations,
    )
    async def resolve_human_request_tool(
        task_id: str,
        request_id: str,
        item_responses: dict[str, JsonValue],
    ) -> HumanRequestResolveResponse:
        request = HumanRequestResolveRequest(item_responses=item_responses)
        async with get_session_factory()() as session:
            return await resolve_human_request(
                session,
                task_id=task_id,
                request_id=request_id,
                request=request,
                actor_ref=_OPERATOR_MCP_ACTOR_REF,
                resolved_by_surface=HumanRequestResolutionSurface.OPERATOR_MCP,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def register_command_run_tools(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> None:
    @server.tool(
        name="get_command_runs",
        title=GET_COMMAND_RUNS_TEACHING.title,
        description=GET_COMMAND_RUNS_TEACHING.description,
        annotations=GET_COMMAND_RUNS_TEACHING.annotations,
    )
    async def get_command_runs(
        task_id: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> CommandRunListResponse:
        return await read_session_operation(
            lambda session: list_command_runs(
                session,
                task_id=task_id,
                cursor=cursor,
                limit=limit,
            )
        )

    @server.tool(
        name="get_command_run",
        title=GET_COMMAND_RUN_TEACHING.title,
        description=GET_COMMAND_RUN_TEACHING.description,
        annotations=GET_COMMAND_RUN_TEACHING.annotations,
    )
    async def get_command_run(task_id: str, run_id: str) -> CommandRunRecord:
        return await read_session_operation(
            lambda session: read_command_run(session, task_id=task_id, run_id=run_id)
        )

    @server.tool(
        name="get_command_run_log",
        title=GET_COMMAND_RUN_LOG_TEACHING.title,
        description=GET_COMMAND_RUN_LOG_TEACHING.description,
        annotations=GET_COMMAND_RUN_LOG_TEACHING.annotations,
    )
    async def get_command_run_log(task_id: str, run_id: str) -> CommandRunLogReadResponse:
        return await read_session_operation(
            lambda session: read_command_run_log(session, task_id=task_id, run_id=run_id)
        )

    @server.tool(
        name="cancel_command_run",
        title=CANCEL_COMMAND_RUN_TEACHING.title,
        description=CANCEL_COMMAND_RUN_TEACHING.description,
        annotations=CANCEL_COMMAND_RUN_TEACHING.annotations,
    )
    async def cancel_command_run_tool(
        task_id: str,
        run_id: str,
    ) -> CommandRunCancelResponse:
        async with get_session_factory()() as session:
            return await cancel_command_run(
                session,
                task_id=task_id,
                run_id=run_id,
                actor_ref=_OPERATOR_MCP_ACTOR_REF,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def _register_pause_task_tool(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    @server.tool(
        name="pause_task",
        title=PAUSE_TASK_TEACHING.title,
        description=PAUSE_TASK_TEACHING.description,
        annotations=PAUSE_TASK_TEACHING.annotations,
    )
    async def pause_task(
        task_id: str,
        expected_active_flow_revision_id: str,
        expected_control_revision: int,
    ) -> RuntimeFlowPauseResponse:
        query = RuntimeFlowControlRequest(
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
        )
        async with get_session_factory()() as session:
            return await pause_runtime_flow(
                session,
                task_id,
                expected_active_flow_revision_id=query.expected_active_flow_revision_id,
                expected_control_revision=query.expected_control_revision,
                actor_ref=_OPERATOR_MCP_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR_MCP,
                runtime_effect_publisher=runtime_effect_publisher,
            )


def _register_continue_task_tool(
    server: FastMCP,
    *,
    dependencies: DispatchOpeningDependencies | None,
) -> None:
    @server.tool(
        name="continue_task",
        title=CONTINUE_TASK_TEACHING.title,
        description=CONTINUE_TASK_TEACHING.description,
        annotations=CONTINUE_TASK_TEACHING.annotations,
    )
    async def continue_task(
        task_id: str,
        expected_active_flow_revision_id: str,
        expected_control_revision: int,
    ) -> RuntimeFlowRead:
        query = RuntimeFlowControlRequest(
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
        )
        active_dependencies = require_dispatch_opening_dependencies(dependencies)
        async with get_session_factory()() as session:
            return await continue_runtime_flow(
                session,
                task_id,
                expected_active_flow_revision_id=query.expected_active_flow_revision_id,
                expected_control_revision=query.expected_control_revision,
                dependencies=active_dependencies,
                actor_ref=_OPERATOR_MCP_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR_MCP,
            )


def _register_cancel_task_tool(
    server: FastMCP,
    *,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
) -> None:
    @server.tool(
        name="cancel_task",
        title=CANCEL_TASK_TEACHING.title,
        description=CANCEL_TASK_TEACHING.description,
        annotations=CANCEL_TASK_TEACHING.annotations,
    )
    async def cancel_task(
        task_id: str,
        expected_active_flow_revision_id: str,
        expected_control_revision: int,
    ) -> RuntimeFlowRead:
        query = RuntimeFlowControlRequest(
            expected_active_flow_revision_id=expected_active_flow_revision_id,
            expected_control_revision=expected_control_revision,
        )
        async with get_session_factory()() as session:
            return await cancel_runtime_flow(
                session,
                task_id,
                expected_active_flow_revision_id=query.expected_active_flow_revision_id,
                expected_control_revision=query.expected_control_revision,
                actor_ref=_OPERATOR_MCP_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR_MCP,
                runtime_effect_publisher=runtime_effect_publisher,
            )

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import banksia.interfaces.http.routers.task_activities as activity_router_module
from banksia.persistence.models import (
    CommandRunModel,
    HumanRequestModel,
    ReplanTransitionModel,
    TaskEventModel,
)
from banksia.runtime.command_run import (
    claim_command_run_launch,
    mark_command_run_running,
    terminalize_command_run,
)
from banksia.runtime.contracts import (
    CommandRunState,
    HumanRequestResolutionSurface,
    TaskEventSource,
    TaskEventType,
)
from banksia.runtime.contracts.task import (
    HumanRequestResponseRequest,
    TaskActivity,
    TaskActivityPage,
)
from banksia.runtime.contracts.task_events import TaskEventRecord
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.product.activities import (
    list_task_activities,
    project_task_event,
)
from banksia.runtime.product.human_requests import (
    read_product_human_request,
    respond_to_product_human_request,
)
from banksia.runtime.replan.continuation import continue_committed_replan
from banksia.runtime.task_events import (
    TaskEventCursorResetRequiredError,
    append_task_event,
    encode_task_event_cursor,
)
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    make_seed_child_terminal,
    seeded_async_executor,
)
from tests.helpers.lineage_seed import FIXTURE_TIMESTAMP, RuntimeIds
from tests.helpers.product_surface import product_dispatch_dependencies, product_http_client

NOW = datetime(2026, 7, 24, 1, 2, 3, tzinfo=UTC)


async def test_human_activity_uses_source_truth_and_rejects_duplicate_corrupt_hints(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="activity-human-source") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        request_id = await _open_human_request(executor, ids)
        async with session_factory() as session:
            corrupt = await _resolve_human_request_with_duplicate_opened_hints(
                session,
                ids=ids,
                request_id=request_id,
            )

        async with session_factory() as session:
            page, suppressed = await _duplicate_terminal_hint_and_read_activity(
                session,
                ids=ids,
                request_id=request_id,
                corrupt=corrupt,
            )

    assert [activity.kind for activity in page.items] == [
        "input_requested",
        "input_received",
    ]
    assert page.items[0].summary == "Choose a direction."
    assert page.items[1].summary is None
    assert all(activity.member is not None for activity in page.items)
    assert {activity.member.name for activity in page.items if activity.member} == {"Root Member"}
    assert suppressed is None


async def test_command_activity_follows_real_terminal_transition(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="activity-command-source") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        opened = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="start_command_run",
            arguments={
                "request": {
                    "command": {"kind": "argv", "argv": ["python", "-V"]},
                    "summary": "Check Python.",
                }
            },
        )
        command_id = str(opened.model_dump()["command_id"])
        async with session_factory() as session:
            claim = await claim_command_run_launch(
                session,
                run_id=command_id,
                owner_ref="test-owner",
                claimed_at=NOW,
            )
            assert claim is not None
            running = await mark_command_run_running(
                session,
                claim=claim,
                owner_ref="test-owner",
                pid=123,
                started_at=NOW,
                due_at=None,
            )
            assert running is not None
            won = await terminalize_command_run(
                session,
                task_id=ids.task_id,
                run_id=command_id,
                expected_ownership_revision=running.ownership_revision,
                expected_states=(CommandRunState.RUNNING,),
                terminal_state=CommandRunState.FAILED,
                summary="Python check failed.",
                ended_at=NOW + timedelta(seconds=5),
                failure_code="process_failed",
                output_observed_bytes=0,
                output_written_bytes=0,
                is_output_complete=True,
            )
            assert won is True

        async with session_factory() as session:
            page = await list_task_activities(session, task_id=ids.task_id)
            source = await session.get(CommandRunModel, command_id)

    assert source is not None and source.state == "failed"
    assert [activity.kind for activity in page.items] == [
        "action_started",
        "action_failed",
    ]
    assert page.items[-1].summary == source.terminal_summary
    assert page.items[-1].action is not None


async def test_historical_activity_member_survives_rename_and_removal(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="activity-member-history") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
            await append_task_event(
                session,
                task_id=ids.task_id,
                event_type=TaskEventType.BOUNDARY_ACCEPTED,
                event_source=TaskEventSource.NODE,
                occurred_at=FIXTURE_TIMESTAMP,
                team_revision_id=ids.team_revision_id,
                dispatch_id=ids.child_dispatch_id,
                attempt_id=ids.child_attempt_id,
                member_id=ids.child_member_id,
                payload={
                    "source_dispatch_id": ids.child_dispatch_id,
                    "assignment_id": ids.child_assignment_id,
                    "attempt_id": ids.child_attempt_id,
                    "outcome": "blocked",
                    "checkpoint_id": ids.child_checkpoint_id,
                    "resulting_task_status": "running",
                },
            )
            await session.commit()

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="update_child",
            arguments={
                "id": ids.child_member_id,
                "patch": {"title": "Renamed Child"},
            },
        )
        async with session_factory() as session:
            transition = await session.scalar(
                select(ReplanTransitionModel).where(
                    ReplanTransitionModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            assert transition is not None
            opening = await continue_committed_replan(
                session,
                transition_id=transition.replan_transition_id,
                dependencies=product_dispatch_dependencies(tmp_path),
            )
        assert opening.dispatch_id is not None
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=opening.dispatch_id,
            ),
            operation_name="remove_child",
            arguments={"id": ids.child_member_id},
        )

        async with session_factory() as session:
            page = await list_task_activities(session, task_id=ids.task_id)

    child_activity = next(activity for activity in page.items if activity.kind == "work_blocked")
    assert child_activity.member is not None
    assert child_activity.member.id == ids.child_member_id
    assert child_activity.member.name == "Child Member"


async def test_activity_cursor_reset_bounded_page_and_sse_reconnect_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="activity-cursor") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        original, corrupt, first = await _prepare_activity_cursor_case(
            executor,
            session_factory=session_factory,
            ids=ids,
        )

        monkeypatch.setattr(
            activity_router_module,
            "get_session_factory",
            lambda: session_factory,
        )
        reset_cursor = encode_task_event_cursor("task-event.missing")
        previous_cursor = encode_task_event_cursor(original.event_id)
        different_cursor = encode_task_event_cursor(corrupt.event_id)
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            reset_page = await client.get(
                f"/api/tasks/{ids.task_id}/activities",
                params={"cursor": reset_cursor},
            )
            reset_stream = await client.get(
                f"/api/tasks/{ids.task_id}/activities/stream",
                params={"cursor": reset_cursor},
            )

        assert first.items
        assert first.next_cursor is not None
        for response in (reset_page, reset_stream):
            assert response.status_code == 410
            assert response.json()["code"] == "cursor_reset_required"

        live = activity_router_module.stream_task_activity_records(
            task_id=ids.task_id,
            cursor=previous_cursor,
        )
        frame = await anext(live)
        await cast(AsyncGenerator[str, None], live).aclose()
        assert "event: task_changed" in frame
        assert "payload" not in frame

        reconnect = await activity_router_module.stream_task_activities(
            ids.task_id,
            cursor=previous_cursor,
            last_event_id=different_cursor,
        )
        reconnect_body = cast(AsyncGenerator[str, None], reconnect.body_iterator)
        reconnect_frame = await anext(reconnect_body)
        await reconnect_body.aclose()
        assert "event: activity" in reconnect_frame
        assert "input_cancelled" in reconnect_frame


async def _resolve_human_request_with_duplicate_opened_hints(
    session: AsyncSession,
    *,
    ids: RuntimeIds,
    request_id: str,
) -> TaskEventRecord:
    source = await session.get(HumanRequestModel, request_id)
    assert source is not None
    original = await session.scalar(
        select(TaskEventModel).where(
            TaskEventModel.task_id == ids.task_id,
            TaskEventModel.event_type == TaskEventType.HUMAN_REQUEST_OPENED.value,
        )
    )
    assert original is not None
    corrupt = await append_task_event(
        session,
        task_id=ids.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_OPENED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=source.opened_at,
        team_revision_id=ids.team_revision_id,
        dispatch_id=ids.child_dispatch_id,
        attempt_id=ids.child_attempt_id,
        member_id=ids.child_member_id,
        payload=original.payload,
    )
    await append_task_event(
        session,
        task_id=ids.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_OPENED,
        event_source=TaskEventSource.CONTROLLER,
        occurred_at=source.opened_at,
        team_revision_id=ids.team_revision_id,
        dispatch_id=source.source_dispatch_id,
        attempt_id=source.attempt_id,
        member_id=ids.root_member_id,
        payload=original.payload,
    )
    await session.commit()
    view = await read_product_human_request(
        session,
        task_id=ids.task_id,
        request_id=request_id,
    )
    assert view.action is not None
    await respond_to_product_human_request(
        session,
        task_id=ids.task_id,
        request_id=request_id,
        request=HumanRequestResponseRequest.model_validate(
            {
                "action_id": view.action.id,
                "input": {
                    "kind": "answer",
                    "item_responses": {
                        "direction": {"kind": "option", "option_id": "a"},
                    },
                },
            }
        ),
        actor_ref="user",
        resolved_by_surface=HumanRequestResolutionSurface.CONTROL_UI,
    )
    return corrupt


async def _duplicate_terminal_hint_and_read_activity(
    session: AsyncSession,
    *,
    ids: RuntimeIds,
    request_id: str,
    corrupt: TaskEventRecord,
) -> tuple[TaskActivityPage, TaskActivity | None]:
    source = await session.get(HumanRequestModel, request_id)
    assert source is not None and source.resolved_at is not None
    terminal = await session.scalar(
        select(TaskEventModel).where(
            TaskEventModel.task_id == ids.task_id,
            TaskEventModel.event_type == TaskEventType.HUMAN_REQUEST_RESOLVED.value,
        )
    )
    assert terminal is not None
    await append_task_event(
        session,
        task_id=ids.task_id,
        event_type=TaskEventType.HUMAN_REQUEST_RESOLVED,
        event_source=TaskEventSource.CONTROL_API,
        occurred_at=source.resolved_at,
        dispatch_id=source.source_dispatch_id,
        attempt_id=source.attempt_id,
        member_id=ids.root_member_id,
        payload=terminal.payload,
    )
    await session.commit()
    page = await list_task_activities(session, task_id=ids.task_id)
    return page, await project_task_event(session, corrupt)


async def _prepare_activity_cursor_case(
    executor: NodeOperationExecutor,
    *,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
) -> tuple[TaskEventModel, TaskEventRecord, TaskActivityPage]:
    request_id = await _open_human_request(executor, ids)
    async with session_factory() as session:
        source = await session.get(HumanRequestModel, request_id)
        assert source is not None
        original = await session.scalar(
            select(TaskEventModel).where(
                TaskEventModel.task_id == ids.task_id,
                TaskEventModel.event_type == TaskEventType.HUMAN_REQUEST_OPENED.value,
            )
        )
        assert original is not None
        corrupt = await append_task_event(
            session,
            task_id=ids.task_id,
            event_type=TaskEventType.HUMAN_REQUEST_OPENED,
            event_source=TaskEventSource.CONTROLLER,
            occurred_at=source.opened_at,
            team_revision_id=ids.team_revision_id,
            dispatch_id=ids.child_dispatch_id,
            attempt_id=ids.child_attempt_id,
            member_id=ids.child_member_id,
            payload=original.payload,
        )
        await session.commit()
        view = await read_product_human_request(
            session,
            task_id=ids.task_id,
            request_id=request_id,
        )
        assert view.cancel_action is not None
        await respond_to_product_human_request(
            session,
            task_id=ids.task_id,
            request_id=request_id,
            request=HumanRequestResponseRequest.model_validate(
                {
                    "action_id": view.cancel_action.id,
                    "input": {"kind": "cancel", "confirmed": True},
                }
            ),
            actor_ref="user",
            resolved_by_surface=HumanRequestResolutionSurface.CONTROL_UI,
        )
        with pytest.raises(TaskEventCursorResetRequiredError):
            await list_task_activities(
                session,
                task_id=ids.task_id,
                cursor=encode_task_event_cursor("task-event.missing"),
            )
        first = await list_task_activities(session, task_id=ids.task_id, limit=1)
    return original, corrupt, first


async def _open_human_request(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose a direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "Direction A"},
                            {"id": "b", "title": "Direction B"},
                        ],
                    }
                ],
            }
        },
    )
    return str(opened.model_dump()["request_id"])

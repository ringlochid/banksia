from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import event, update

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AssignmentWorkPlanModel,
    AssignmentWorkPlanStepModel,
    AttemptCheckpointModel,
    AttemptModel,
    DispatchTurnModel,
    HumanRequestModel,
    TaskModel,
)
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import TaskEventSource
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.task import (
    TaskControlReceipt,
    TaskControlRequest,
    TaskView,
)
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.product.activities import list_task_activities
from banksia.runtime.product.tasks import (
    control_product_task,
    read_product_task,
    search_product_tasks,
    start_product_task,
)
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    seeded_async_executor,
    seeded_task_workspace,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.product_surface import (
    product_dispatch_dependencies,
    product_http_client,
)
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_http_product_task_read_uses_bounded_product_truth(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="product-read-parity") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        committed_at = utc_now()
        async with session_factory() as session:
            await session.execute(
                update(AssignmentModel)
                .where(AssignmentModel.assignment_id == ids.child_assignment_id)
                .values(work_plan_revision=1)
            )
            session.add(
                AssignmentWorkPlanModel(
                    assignment_id=ids.child_assignment_id,
                    revision=1,
                    explanation="Review the evidence independently.",
                    authoring_dispatch_id=ids.child_dispatch_id,
                    committed_at=committed_at,
                )
            )
            session.add(
                AssignmentWorkPlanStepModel(
                    work_plan_step_id="work-plan-step.product-read-parity.child.1",
                    assignment_id=ids.child_assignment_id,
                    order_index=0,
                    step="Challenge unsupported claims.",
                    status="in_progress",
                )
            )
            await session.commit()
        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            response = await client.get(f"/api/tasks/{ids.task_id}")
            search = await client.get("/api/tasks", params={"q": "root assignment"})

    assert response.status_code == 200, response.text
    http_task = TaskView.model_validate(response.json())
    assert search.status_code == 200, search.text
    assert [item["id"] for item in search.json()["items"]] == [ids.task_id]
    assert http_task.team.name == "Root Member"
    assert [child.name for child in http_task.team.children] == ["Child Member"]
    child_plan = http_task.team.children[0].plan
    assert child_plan is not None
    assert child_plan.explanation == "Review the evidence independently."
    assert [step.text for step in child_plan.steps] == ["Challenge unsupported claims."]
    assert {action.kind for action in http_task.actions} == {"pause", "cancel"}
    assert http_task.result is None

    serialized = json.dumps(response.json(), sort_keys=True).casefold()
    for forbidden in (
        "assignment_id",
        "attempt_id",
        "dispatch_id",
        "boundary",
        "control_revision",
        "team_revision",
        "event_hash",
        "provider_route",
        "watchdog",
        "raw_payload",
    ):
        assert forbidden not in serialized


async def test_http_task_pause_uses_current_action_id_and_returns_receipt(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_async_executor(tmp_path, suffix="product-pause-http") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            current = await read_product_task(session, ids.task_id)
        pause_action = next(action for action in current.actions if action.kind == "pause")
        async with product_http_client(
            session_factory,
            tmp_path=tmp_path,
            publisher=publisher,
        ) as client:
            response = await client.post(pause_action.href, json={"confirmed": False})
            stale = await client.post(
                f"/api/tasks/{ids.task_id}/controls/action.stale",
                json={"confirmed": False},
            )
        assert response.status_code == 200, response.text
        receipt = TaskControlReceipt.model_validate(response.json())
        assert stale.status_code == 409
        assert stale.json()["code"] == "conflict"
        assert "control_revision" not in stale.text

    assert receipt.action == "pause"
    assert receipt.receipt_id.startswith("receipt.")
    assert receipt.task.status == "paused"
    assert [action.kind for action in receipt.task.actions] == ["resume", "cancel"]


async def test_task_view_embeds_the_most_recent_twenty_activities(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = product_dispatch_dependencies(tmp_path)
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        workspace = tmp_path / "recent-activity-workspace"
        workspace.mkdir()
        async with session_factory() as session:
            started = await start_product_task(
                TaskStartRequest(
                    workflow=GENERIC_WORKFLOW_ID,
                    prompt="Exercise recent Activity projection.",
                    workspace=workspace,
                ),
                dependencies=dependencies,
                session=session,
            )
        for _index in range(11):
            async with session_factory() as session:
                current = await read_product_task(session, started.task_id)
                pause_action = next(action for action in current.actions if action.kind == "pause")
                await control_product_task(
                    session,
                    task_id=started.task_id,
                    action_id=pause_action.id,
                    request=TaskControlRequest(),
                    dependencies=dependencies,
                    actor_ref="user",
                    event_source=TaskEventSource.CONTROL_API,
                    runtime_effect_publisher=publisher,
                )
            async with session_factory() as session:
                current = await read_product_task(session, started.task_id)
                resume_action = next(
                    action for action in current.actions if action.kind == "resume"
                )
                await control_product_task(
                    session,
                    task_id=started.task_id,
                    action_id=resume_action.id,
                    request=TaskControlRequest(),
                    dependencies=dependencies,
                    actor_ref="user",
                    event_source=TaskEventSource.CONTROL_API,
                    runtime_effect_publisher=publisher,
                )

        async with session_factory() as session:
            view = await read_product_task(session, started.task_id)
            full_activity = await list_task_activities(
                session,
                task_id=started.task_id,
                limit=100,
            )

    assert len(full_activity.items) == 23
    assert all(activity.summary is None for activity in full_activity.items)
    assert len(view.activities) == 20
    assert view.is_activity_history_truncated is True
    assert [activity.id for activity in view.activities] == [
        activity.id for activity in full_activity.items[-20:]
    ]
    assert view.activities[0].kind == "task_paused"
    assert view.activities[-1].kind == "task_resumed"


async def test_exact_root_checkpoint_is_the_only_result_and_terminal_activity(
    tmp_path: Path,
) -> None:
    suffix = "product-exact-result"
    async with seeded_async_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await _complete_child_boundary(session_factory, ids)
        workspace = seeded_task_workspace(tmp_path, suffix)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "result.md").write_text("Exact result body.\n", encoding="utf-8")
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="checkpoint",
            arguments={
                "summary": "Integrated the exact requested result.",
                "details": "No presentation fallback was used.",
                "files": [{"path": "result.md", "description": "Exact result reference."}],
                "outcome": "green",
            },
        )
        async with session_factory() as session:
            view = await read_product_task(session, ids.task_id)

    assert view.result is not None
    assert view.result.status == "completed"
    assert view.result.summary == "Integrated the exact requested result."
    assert view.result.details == "No presentation fallback was used."
    assert [file.path for file in view.result.files] == ["result.md"]
    root_terminal = [
        activity
        for activity in view.activities
        if activity.kind in {"task_completed", "task_blocked"}
    ]
    assert len(root_terminal) == 1
    assert root_terminal[0].summary is None
    assert root_terminal[0].files == ()
    assert view.team.latest_update is None
    assert any(child.latest_update is not None for child in view.team.children)


async def test_task_search_uses_stable_keyset_and_one_summary_query(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        original_ids: list[str] = []
        for index in range(5):
            workspace = tmp_path / f"search-workspace-{index}"
            workspace.mkdir()
            async with session_factory() as session:
                receipt = await start_product_task(
                    TaskStartRequest(
                        workflow=GENERIC_WORKFLOW_ID,
                        prompt=f"Searchable work {index}",
                        workspace=workspace,
                    ),
                    dependencies=product_dispatch_dependencies(tmp_path),
                    session=session,
                )
                original_ids.append(receipt.task_id)

        async with session_factory() as session:
            query_count = 0
            bind = session.get_bind()

            def count_query(
                _connection: object,
                _cursor: object,
                statement: str,
                *_args: object,
            ) -> None:
                nonlocal query_count
                if statement.lstrip().upper().startswith("SELECT"):
                    query_count += 1

            event.listen(bind, "before_cursor_execute", count_query)
            try:
                baseline = await search_product_tasks(session, limit=100)
            finally:
                event.remove(bind, "before_cursor_execute", count_query)
            first = await search_product_tasks(session, limit=2)

        assert query_count == 1
        assert first.next_cursor is not None
        baseline_ids = [item.id for item in baseline.items]
        assert set(baseline_ids) == set(original_ids)

        async with session_factory() as session:
            await session.execute(
                update(TaskModel)
                .where(TaskModel.task_id == baseline_ids[-1])
                .values(updated_at=utc_now() + timedelta(hours=1))
            )
            await session.commit()
        new_workspace = tmp_path / "search-workspace-new"
        new_workspace.mkdir()
        async with session_factory() as session:
            concurrent = await start_product_task(
                TaskStartRequest(
                    workflow=GENERIC_WORKFLOW_ID,
                    prompt="Concurrent newer work",
                    workspace=new_workspace,
                ),
                dependencies=product_dispatch_dependencies(tmp_path),
                session=session,
            )

        paged_ids = [item.id for item in first.items]
        cursor: str | None = first.next_cursor
        while cursor is not None:
            async with session_factory() as session:
                page = await search_product_tasks(session, cursor=cursor, limit=2)
            paged_ids.extend(item.id for item in page.items)
            cursor = page.next_cursor

    assert paged_ids == baseline_ids
    assert concurrent.task_id not in paged_ids


async def test_task_view_keeps_older_open_request_before_bounded_terminal_history(
    tmp_path: Path,
) -> None:
    suffix = "product-current-attention"
    async with seeded_async_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        open_request_id = await _open_older_human_request(executor, ids=ids)
        await _seed_terminal_human_request_history(
            session_factory,
            ids=ids,
            open_request_id=open_request_id,
            suffix=suffix,
        )

        async with session_factory() as session:
            view = await read_product_task(session, ids.task_id)

    assert view.status == "waiting_for_you"
    assert view.human_request_count == 22
    assert view.is_human_request_history_truncated is True
    assert len(view.human_requests) == 21
    assert view.human_requests[0].id == open_request_id
    assert view.human_requests[0].status == "open"
    assert view.activities_href == f"/api/tasks/{ids.task_id}/activities"


async def _open_older_human_request(
    executor: NodeOperationExecutor,
    *,
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
                "summary": "Older input is still required.",
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


async def _seed_terminal_human_request_history(
    session_factory: AsyncSessionFactory,
    *,
    ids: RuntimeIds,
    open_request_id: str,
    suffix: str,
) -> None:
    async with session_factory() as session:
        source_dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        open_request = await session.get(HumanRequestModel, open_request_id)
        assert source_dispatch is not None and open_request is not None
        for index in range(21):
            occurred_at = open_request.opened_at + timedelta(seconds=index + 1)
            attempt_id = f"attempt.{suffix}.terminal.{index}"
            dispatch_id = f"dispatch.{suffix}.terminal.{index}"
            session.add(
                AttemptModel(
                    attempt_id=attempt_id,
                    assignment_id=ids.root_assignment_id,
                    task_id=ids.task_id,
                    retry_of_attempt_id=None,
                    latest_checkpoint_id=None,
                    current_dispatch_id=None,
                    current_wait_id=None,
                    status="cancelled",
                    terminal_outcome=None,
                    opened_at=occurred_at,
                    closed_at=occurred_at,
                )
            )
            session.add(
                DispatchTurnModel(
                    **_closed_dispatch_values(
                        source_dispatch,
                        dispatch_id=dispatch_id,
                        attempt_id=attempt_id,
                        occurred_at=occurred_at,
                    )
                )
            )
            session.add(
                HumanRequestModel(
                    request_id=f"human-request.{suffix}.terminal.{index}",
                    task_id=ids.task_id,
                    assignment_id=ids.root_assignment_id,
                    attempt_id=attempt_id,
                    source_dispatch_id=dispatch_id,
                    request_kind=open_request.request_kind,
                    request_summary=f"Terminal request {index}",
                    request_items_json=open_request.request_items_json,
                    status="cancelled",
                    resolution_kind="cancelled",
                    resolution_summary="No longer needed.",
                    resolved_by_actor_ref="user",
                    resolved_by_surface="control_ui",
                    opened_at=occurred_at,
                    resolved_at=occurred_at,
                )
            )
        await session.commit()


async def _complete_child_boundary(
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
) -> None:
    now = utc_now()
    async with session_factory() as session:
        child_checkpoint = await session.get(AttemptCheckpointModel, ids.child_checkpoint_id)
        child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
        child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        assert child_checkpoint is not None
        assert child_attempt is not None
        assert child_assignment is not None
        child_checkpoint.outcome = "green"
        child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
        child_attempt.status = "completed"
        child_attempt.terminal_outcome = "green"
        child_attempt.closed_at = now
        child_assignment.terminal_outcome = "green"
        child_assignment.closed_at = now
        session.add(
            AcceptedBoundaryModel(
                accepted_boundary_id=f"accepted-boundary.{ids.child_dispatch_id}",
                source_dispatch_id=ids.child_dispatch_id,
                task_id=ids.task_id,
                assignment_id=ids.child_assignment_id,
                attempt_id=ids.child_attempt_id,
                outcome="green",
                checkpoint_id=ids.child_checkpoint_id,
                successor_dispatch_id=None,
                committed_at=now,
            )
        )
        await session.commit()


def _closed_dispatch_values(
    source: DispatchTurnModel,
    *,
    dispatch_id: str,
    attempt_id: str,
    occurred_at: datetime,
) -> dict[str, object]:
    values = {
        column.name: getattr(source, column.name)
        for column in DispatchTurnModel.__table__.columns
        if column.computed is None
    }
    values.update(
        {
            "dispatch_id": dispatch_id,
            "attempt_id": attempt_id,
            "task_start_source_task_id": None,
            "predecessor_dispatch_id": None,
            "status": "closed",
            "opened_reason": "semantic_retry",
            "created_at": occurred_at,
            "adapter_started_at": occurred_at,
            "last_node_activity_at": occurred_at,
            "closed_at": occurred_at,
            "closed_reason": "human_request_wait",
        }
    )
    return values

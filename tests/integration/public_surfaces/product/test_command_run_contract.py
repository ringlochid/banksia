from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from oh_my_subagents.persistence.models import CommandRunModel
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.command_run import (
    claim_command_run_launch,
    mark_command_run_running,
    terminalize_command_run,
)
from oh_my_subagents.runtime.contracts import CommandRunState
from oh_my_subagents.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunPage,
    CommandRunView,
)
from oh_my_subagents.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from oh_my_subagents.runtime.product.command_runs import (
    cancel_product_command_run,
    read_product_command_output,
    read_product_command_run,
)
from oh_my_subagents.runtime.product.tasks import read_product_task, search_product_tasks
from tests.helpers.executor_harness import (
    AsyncSessionFactory,
    seeded_async_executor,
    seeded_task_workspace,
)
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.product_surface import (
    product_http_client,
)


async def test_http_command_run_view_output_and_cancel_use_product_contract(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    suffix = "product-command-http"
    async with seeded_async_executor(
        tmp_path,
        suffix=suffix,
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _signals):
        command_id, command_view, output = await _open_product_command_run(
            executor,
            session_factory,
            ids,
            workspace=seeded_task_workspace(tmp_path, suffix),
        )
        assert command_view.cancel_action is not None
        cancel_action = command_view.cancel_action
        async with product_http_client(
            session_factory,
            tmp_path=tmp_path,
            publisher=publisher,
        ) as client:
            response = await client.post(
                f"/api/tasks/{ids.task_id}/command-runs/{command_id}/cancel",
                json={"action_id": cancel_action.id, "confirmed": True},
            )
        assert response.status_code == 200, response.text
        receipt = CommandRunCancelReceipt.model_validate(response.json())

        async with session_factory() as session:
            source = await session.get(CommandRunModel, command_id)

    assert command_view.state == "queued"
    assert output.content == "red\n"
    assert output.is_missing is False
    serialized = command_view.model_dump_json().casefold()
    for forbidden in ("argv", "workdir", "exit_code", "output_path", "ownership_revision"):
        assert forbidden not in serialized
    assert receipt.receipt_id.startswith("receipt.")
    assert receipt.command_run.state == "cancelling"
    assert receipt.command_run.cancel_action is None
    assert source is not None and source.state == "cancellation_requested"


async def test_http_command_history_pages_every_product_safe_action(
    tmp_path: Path,
) -> None:
    suffix = "product-command-history"
    async with seeded_async_executor(tmp_path, suffix=suffix) as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        await _seed_product_command_history(session_factory, ids=ids)

        async with product_http_client(session_factory, tmp_path=tmp_path) as client:
            first_response = await client.get(
                f"/api/tasks/{ids.task_id}/command-runs",
                params={"limit": 2},
            )
            assert first_response.status_code == 200, first_response.text
            first = CommandRunPage.model_validate(first_response.json())
            assert first.next_cursor is not None
            assert "c_history_middle" not in first.next_cursor
            second_response = await client.get(
                f"/api/tasks/{ids.task_id}/command-runs",
                params={"cursor": first.next_cursor, "limit": 2},
            )
            invalid_response = await client.get(
                f"/api/tasks/{ids.task_id}/command-runs",
                params={"cursor": "not-a-command-history-cursor"},
            )

        second = CommandRunPage.model_validate(second_response.json())
        async with session_factory() as session:
            task = await read_product_task(session, ids.task_id)

    assert [command.id for command in first.items] == [
        "c_history_newest",
        "c_history_middle",
    ]
    assert [command.id for command in second.items] == ["c_history_oldest"]
    assert second.next_cursor is None
    assert invalid_response.status_code == 400
    assert task.command_runs_href == f"/api/tasks/{ids.task_id}/command-runs"


async def _seed_product_command_history(
    session_factory: AsyncSessionFactory,
    *,
    ids: RuntimeIds,
) -> None:
    now = utc_now()
    sources = (
        (
            "c_history_oldest",
            ids.root_assignment_id,
            ids.root_attempt_id,
            ids.root_dispatch_id,
            now - timedelta(minutes=2),
        ),
        (
            "c_history_middle",
            ids.child_assignment_id,
            ids.child_attempt_id,
            ids.child_dispatch_id,
            now - timedelta(minutes=1),
        ),
        (
            "c_history_newest",
            ids.root_assignment_id,
            ids.root_attempt_id,
            ids.current_dispatch_id,
            now,
        ),
    )
    async with session_factory() as session:
        session.add_all(
            CommandRunModel(
                run_id=run_id,
                task_id=ids.task_id,
                assignment_id=assignment_id,
                attempt_id=attempt_id,
                source_dispatch_id=dispatch_id,
                command_spec_json={"kind": "argv", "argv": ["true"]},
                cwd=None,
                summary=f"Command {run_id}",
                timeout_seconds=None,
                due_at=None,
                output_path=f".oms/{ids.task_id}/command-runs/{run_id}/output.log",
                output_complete=True,
                state="succeeded",
                ownership_revision=1,
                terminal_summary="Succeeded.",
                terminal_exit_code=0,
                terminal_event_source="controller",
                created_at=created_at,
                started_at=created_at,
                ended_at=created_at,
            )
            for run_id, assignment_id, attempt_id, dispatch_id, created_at in sources
        )
        await session.commit()


async def _open_product_command_run(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    *,
    workspace: Path,
) -> tuple[str, CommandRunView, CommandRunOutputPage]:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Check the local Python version.",
            }
        },
    )
    command_id = str(opened.model_dump()["command_id"])
    async with session_factory() as session:
        source = await session.get(CommandRunModel, command_id)
        assert source is not None
        output_path = workspace / source.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x1b[31mred\x1b[0m\x00\n")
        command_view = await read_product_command_run(
            session,
            task_id=ids.task_id,
            command_id=command_id,
        )
        output = await read_product_command_output(
            session,
            task_id=ids.task_id,
            command_id=command_id,
        )
    return command_id, command_view, output


async def test_command_output_pages_are_utf8_safe_and_strip_hostile_terminal_controls(
    tmp_path: Path,
) -> None:
    suffix = "product-command-hostile-output"
    async with seeded_async_executor(tmp_path, suffix=suffix) as (
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
                    "summary": "Render hostile output.",
                }
            },
        )
        command_id = str(opened.model_dump()["command_id"])
        hostile = (
            "A\x00B\x7fC"
            "\x1b[31mred\x1b[0m"
            "\x9b32mgreen\x9b0m"
            "\x1b]title\x07"
            "\x1bPsecret-dcs\x1b\\"
            "\x1bXsecret-sos\x1b\\"
            "\x1b^secret-pm\x1b\\"
            "\x1b_secret-apc\x1b\\"
            "\u202espoof\u202c"
            " café 🐍\n"
        )
        async with session_factory() as session:
            source = await session.get(CommandRunModel, command_id)
            assert source is not None
            output_path = seeded_task_workspace(tmp_path, suffix) / source.output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(hostile.encode("utf-8"))

        cursor = None
        pages: list[str] = []
        for _index in range(len(hostile.encode("utf-8")) + 1):
            async with session_factory() as session:
                page = await read_product_command_output(
                    session,
                    task_id=ids.task_id,
                    command_id=command_id,
                    cursor=cursor,
                    limit=1,
                )
            pages.append(page.content)
            cursor = page.next_cursor
            if cursor is None:
                break
        else:  # pragma: no cover - proves every generated cursor advances
            pytest.fail("generated output cursor did not reach end of file")

    rendered = "".join(pages)
    assert rendered == "ABCredgreenspoof café 🐍\n"
    assert "\ufffd" not in rendered
    assert "secret" not in rendered


async def test_live_elapsed_and_failed_command_stays_out_of_attention(
    tmp_path: Path,
) -> None:
    suffix = "product-command-fidelity"
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_async_executor(
        tmp_path,
        suffix=suffix,
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _signals):
        (
            command_id,
            started_at,
            ownership_revision,
        ) = await _open_running_command_and_request_cancellation(
            executor,
            session_factory=session_factory,
            ids=ids,
            publisher=publisher,
        )

        observed_at = started_at + timedelta(seconds=30)
        async with session_factory() as session:
            cancelling = await read_product_command_run(
                session,
                task_id=ids.task_id,
                command_id=command_id,
                observed_at=observed_at,
            )
            won = await terminalize_command_run(
                session,
                task_id=ids.task_id,
                run_id=command_id,
                expected_ownership_revision=ownership_revision,
                expected_states=(CommandRunState.CANCELLATION_REQUESTED,),
                terminal_state=CommandRunState.FAILED,
                summary="The action failed while stopping.",
                ended_at=observed_at + timedelta(seconds=5),
                failure_code="process_failed",
                output_observed_bytes=0,
                output_written_bytes=0,
                is_output_complete=True,
            )
            assert won is True
        async with session_factory() as session:
            task = await read_product_task(session, ids.task_id)
            search = await search_product_tasks(session, q=ids.task_id)

    assert cancelling.state == "cancelling"
    assert cancelling.elapsed_seconds == 30
    failed = next(command for command in task.command_runs if command.id == command_id)
    assert failed.state == "failed"
    assert failed.output_href.endswith(f"/command-runs/{command_id}/output")
    assert task.attention == ()
    assert len(search.items) == 1
    assert search.items[0].attention_count == 0


async def _open_running_command_and_request_cancellation(
    executor: NodeOperationExecutor,
    *,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
    publisher: CapturedRuntimeEffectPublisher,
) -> tuple[str, datetime, int]:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="start_command_run",
        arguments={
            "request": {
                "command": {"kind": "argv", "argv": ["python", "-V"]},
                "summary": "Check elapsed time.",
            }
        },
    )
    command_id = str(opened.model_dump()["command_id"])
    started_at = utc_now() - timedelta(seconds=20)
    async with session_factory() as session:
        claim = await claim_command_run_launch(
            session,
            run_id=command_id,
            owner_ref="test-owner",
            claimed_at=started_at,
        )
        assert claim is not None
        running = await mark_command_run_running(
            session,
            claim=claim,
            owner_ref="test-owner",
            pid=123,
            started_at=started_at,
            due_at=None,
        )
        assert running is not None
        view = await read_product_command_run(
            session,
            task_id=ids.task_id,
            command_id=command_id,
            observed_at=started_at + timedelta(seconds=10),
        )
        assert view.cancel_action is not None
        await cancel_product_command_run(
            session,
            task_id=ids.task_id,
            command_id=command_id,
            request=CommandRunCancelRequest(
                action_id=view.cancel_action.id,
                is_confirmed=True,
            ),
            actor_ref="user",
            runtime_effect_publisher=publisher,
        )
    return command_id, started_at, running.ownership_revision

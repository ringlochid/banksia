from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from banksia.persistence.models import CommandRunModel
from banksia.runtime.clock import utc_now
from banksia.runtime.command_run import (
    claim_command_run_launch,
    mark_command_run_running,
    terminalize_command_run,
)
from banksia.runtime.contracts import CommandRunState
from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunView,
)
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.product.command_runs import (
    cancel_product_command_run,
    read_product_command_output,
    read_product_command_run,
)
from banksia.runtime.product.tasks import read_product_task
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


async def test_live_elapsed_ignores_cancellation_time_and_failed_attention_links_output(
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

    assert cancelling.state == "cancelling"
    assert cancelling.elapsed_seconds == 30
    failed = next(item for item in task.attention if item.kind == "action_failed")
    assert failed.link is not None
    assert failed.link.href.endswith(f"/command-runs/{command_id}/output")


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

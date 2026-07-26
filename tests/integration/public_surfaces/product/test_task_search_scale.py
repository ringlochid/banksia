from __future__ import annotations

from pathlib import Path

from sqlalchemy import event

from banksia.persistence.models import AssignmentModel
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.text import MAX_WORK_PROMPT_BYTES
from banksia.runtime.product.tasks import search_product_tasks, start_product_task
from banksia.runtime.task_control.presentation import (
    TASK_SUMMARY_MAX_CHARACTERS,
    task_prompt_excerpt,
)
from tests.helpers.generic_workflow import GENERIC_WORKFLOW_ID, publish_generic_workflow
from tests.helpers.postgres_runtime_race import postgres_runtime_harness
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import initialized_workflow_database


async def test_task_search_bounds_maximum_page_prompt_projection_to_one_query(
    tmp_path: Path,
) -> None:
    dependencies = product_dispatch_dependencies(tmp_path)
    expected_ids: set[str] = set()
    whitespace_edge_id: str | None = None
    whitespace_edge_prompt: str | None = None
    async with initialized_workflow_database(tmp_path) as session_factory:
        await publish_generic_workflow(session_factory)
        for index in range(100):
            workspace = tmp_path / f"max-search-workspace-{index:03d}"
            workspace.mkdir()
            prompt = _maximum_prompt(index)
            async with session_factory() as session:
                receipt = await start_product_task(
                    TaskStartRequest(
                        workflow=GENERIC_WORKFLOW_ID,
                        prompt=prompt,
                        workspace=workspace,
                    ),
                    dependencies=dependencies,
                    session=session,
                )
            expected_ids.add(receipt.task_id)
            if index == 0:
                whitespace_edge_id = receipt.task_id
                whitespace_edge_prompt = prompt

        async with session_factory() as session:
            query_count = 0
            selected_sql: list[str] = []
            bind = session.get_bind()

            def capture_select(
                _connection: object,
                _cursor: object,
                statement: str,
                *_args: object,
            ) -> None:
                nonlocal query_count
                if statement.lstrip().upper().startswith("SELECT"):
                    query_count += 1
                    selected_sql.append(statement)

            event.listen(bind, "before_cursor_execute", capture_select)
            try:
                result = await search_product_tasks(session, limit=100)
            finally:
                event.remove(bind, "before_cursor_execute", capture_select)

    assert query_count == 1
    assert len(selected_sql) == 1
    assert "substr(" in selected_sql[0].casefold()
    assert result.next_cursor is None
    assert {item.id for item in result.items} == expected_ids
    assert len(result.items) == 100
    for item in result.items:
        assert item.prompt_excerpt
        assert item.prompt_excerpt == " ".join(item.prompt_excerpt.split())
        assert len(item.prompt_excerpt) <= 240
        assert len(item.prompt_excerpt.encode()) < MAX_WORK_PROMPT_BYTES
    assert whitespace_edge_id is not None
    assert whitespace_edge_prompt is not None
    whitespace_edge = next(item for item in result.items if item.id == whitespace_edge_id)
    expected_excerpt = task_prompt_excerpt(
        whitespace_edge_prompt,
        max_characters=TASK_SUMMARY_MAX_CHARACTERS,
    )
    assert whitespace_edge.prompt_excerpt == expected_excerpt
    assert expected_excerpt.startswith("A important context ")

    async with session_factory() as session:
        search_result = await search_product_tasks(
            session,
            q="hidden-search-term",
            limit=100,
        )
    assert [item.id for item in search_result.items] == [whitespace_edge_id]
    assert search_result.items[0].prompt_excerpt == expected_excerpt


async def test_postgresql_task_search_normalizes_before_truncating() -> None:
    prompt = _whitespace_edge_prompt()
    async with postgres_runtime_harness(suffix="task-search-normalization") as harness:
        async with harness.session_factory() as session:
            assignment = await session.get(AssignmentModel, harness.ids.root_assignment_id)
            assert assignment is not None
            assignment.prompt = prompt
            await session.commit()
        async with harness.session_factory() as session:
            result = await search_product_tasks(
                session,
                q="hidden-search-term",
                limit=100,
            )

    assert [item.id for item in result.items] == [harness.ids.task_id]
    assert result.items[0].prompt_excerpt == task_prompt_excerpt(
        prompt,
        max_characters=TASK_SUMMARY_MAX_CHARACTERS,
    )


def _maximum_prompt(index: int) -> str:
    if index == 0:
        return _whitespace_edge_prompt()
    prefix = f"Maximum prompt {index:03d} \n with\tcollapsed   whitespace "
    prompt = prefix + ("x" * (MAX_WORK_PROMPT_BYTES - len(prefix.encode())))
    assert len(prompt.encode()) == MAX_WORK_PROMPT_BYTES
    return prompt


def _whitespace_edge_prompt() -> str:
    prefix = "A" + (" " * 239) + "important context "
    suffix = " hidden-search-term"
    padding = MAX_WORK_PROMPT_BYTES - len(prefix.encode()) - len(suffix.encode())
    prompt = prefix + ("x" * padding) + suffix
    assert len(prompt.encode()) == MAX_WORK_PROMPT_BYTES
    return prompt

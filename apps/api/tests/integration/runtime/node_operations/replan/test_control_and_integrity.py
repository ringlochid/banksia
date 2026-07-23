from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast

import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import DispatchTurnModel, FlowModel, ReplanTransitionModel
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.flow.service import (
    cancel_runtime_flow,
    continue_runtime_flow,
    pause_runtime_flow,
)
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.post_commit.bootstrap import read_replan_continuation_page
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import seeded_executor


async def test_pause_after_replan_resumes_the_exact_transition_once(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-pause-resume") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        dependencies = _opening_dependencies()
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            flow = await session.get(FlowModel, ids.flow_id)
            assert transition is not None and flow is not None
            paused = await pause_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=transition.successor_flow_revision_id,
                expected_control_revision=flow.control_revision,
            )
            startup_while_paused = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=dependencies,
            )
            resumed = await continue_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=transition.successor_flow_revision_id,
                expected_control_revision=paused.flow.control_revision,
                dependencies=dependencies,
            )
            duplicate = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=dependencies,
            )
            current_transition = await session.get(
                ReplanTransitionModel,
                transition.replan_transition_id,
            )
            successor_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(
                    DispatchTurnModel.predecessor_dispatch_id == ids.current_dispatch_id,
                )
            )

    assert startup_while_paused.outcome == "skipped"
    assert resumed.status.value == "running"
    assert resumed.current_dispatch is not None
    assert duplicate.outcome == "skipped"
    assert current_transition is not None
    assert current_transition.successor_state == "opened"
    assert current_transition.successor_dispatch_id == resumed.current_dispatch.dispatch_id
    assert successor_count == 1


async def test_cancel_after_replan_settles_and_hides_the_transition_from_startup(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-cancel") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            flow = await session.get(FlowModel, ids.flow_id)
            assert transition is not None and flow is not None
            cancelled = await cancel_runtime_flow(
                cast(AsyncSession, session),
                ids.task_id,
                expected_active_flow_revision_id=transition.successor_flow_revision_id,
                expected_control_revision=flow.control_revision,
            )
            current_transition = await session.get(
                ReplanTransitionModel,
                transition.replan_transition_id,
            )
        page = await read_replan_continuation_page(
            lambda: cast(
                AbstractAsyncContextManager[AsyncSession],
                session_factory(),
            ),
            cursor=None,
            page_size=10,
        )

    assert cancelled.status.value == "cancelled"
    assert current_transition is not None
    assert current_transition.successor_state == "cancelled"
    assert current_transition.successor_dispatch_id is None
    assert page.sources == ()


async def test_replan_source_dispatch_rejects_revision_snapshot_mismatch(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-source-snapshot-fk") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            assert transition is not None
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(ReplanTransitionModel)
                    .where(
                        ReplanTransitionModel.replan_transition_id
                        == transition.replan_transition_id
                    )
                    .values(
                        source_flow_revision_id=transition.successor_flow_revision_id,
                        source_team_revision_id=transition.successor_team_revision_id,
                    )
                )
                await session.commit()
            await session.rollback()


async def test_replan_successor_dispatch_rejects_revision_snapshot_mismatch(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-successor-snapshot-fk") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            assert transition is not None
            opened = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=_opening_dependencies(),
            )
            assert opened.outcome == "opened"
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(ReplanTransitionModel)
                    .where(
                        ReplanTransitionModel.replan_transition_id
                        == transition.replan_transition_id
                    )
                    .values(
                        successor_flow_revision_id=transition.source_flow_revision_id,
                        successor_team_revision_id=transition.source_team_revision_id,
                    )
                )
                await session.commit()
            await session.rollback()


async def test_replan_successor_dispatch_rejects_wrong_predecessor(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-successor-lineage-fk") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            assert transition is not None
            opened = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=_opening_dependencies(),
            )
            assert opened.outcome == "opened"
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(ReplanTransitionModel)
                    .where(
                        ReplanTransitionModel.replan_transition_id
                        == transition.replan_transition_id
                    )
                    .values(
                        successor_dispatch_id=transition.source_dispatch_id,
                        successor_flow_revision_id=transition.source_flow_revision_id,
                        successor_team_revision_id=transition.source_team_revision_id,
                    )
                )
                await session.commit()
            await session.rollback()


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast

import banksia.runtime.replan.continuation as replan_continuation
import banksia.runtime.replan.persistence as replan_persistence
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptCheckpointModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    MemberModel,
    ReplanTransitionModel,
    TaskModel,
    TeamRevisionModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.flow.service import (
    cancel_runtime_flow,
    pause_runtime_flow,
)
from banksia.runtime.node_operations import NodeActivitySignal, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher, ReplanCommitted
from banksia.runtime.post_commit.bootstrap import read_replan_continuation_page
from banksia.runtime.replan.continuation import continue_committed_replan
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from tests.helpers.executor_harness import (
    seeded_executor,
    synchronized_transition_claims,
)
from tests.helpers.team_persistence_seed import team_revision_id


async def test_manifest_barrier_opens_one_same_attempt_successor(
    tmp_path: Path,
) -> None:
    effects = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="recursive-continuation",
        runtime_effect_publisher=effects,
    ) as (executor, session_factory, ids, _signals):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        replan_signal = effects.signals[0]
        assert isinstance(replan_signal, ReplanCommitted)
        dependencies = _opening_dependencies()
        async with session_factory() as session:
            first = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=replan_signal.transition_id,
                dependencies=dependencies,
            )
            first_transition = await session.get(
                ReplanTransitionModel,
                replan_signal.transition_id,
            )
            assert first.outcome == "opened", (
                first_transition.manifest_state if first_transition else None,
                first_transition.successor_state if first_transition else None,
                first_transition.failure_code if first_transition else None,
                first_transition.failure_detail if first_transition else None,
            )
            duplicate = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=replan_signal.transition_id,
                dependencies=dependencies,
            )
            transition = await session.get(
                ReplanTransitionModel,
                replan_signal.transition_id,
            )
            flow = await session.get(FlowModel, ids.flow_id)
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            refs = await session.get(DispatchPromptRefsModel, first.dispatch_id)
            successor_node = await session.scalar(
                select(FlowNodeModel)
                .options(selectinload(FlowNodeModel.current_assignment))
                .where(
                    FlowNodeModel.flow_revision_id == transition.successor_flow_revision_id,
                    FlowNodeModel.member_id == "root",
                )
            )

        assert duplicate.outcome == "skipped"
        assert transition is not None and transition.successor_state == "opened"
        assert transition.manifest_state == "current"
        assert flow is not None and flow.current_dispatch_id == first.dispatch_id
        assert successor is not None
        assert successor.opened_reason == "structural_replan"
        assert successor.assignment_id == ids.root_assignment_id
        assert successor.attempt_id == ids.root_attempt_id
        assert successor.flow_revision_id == flow.active_flow_revision_id
        assert successor_node is not None
        assert successor_node.flow_node_id != ids.root_node_id
        assert successor_node.current_assignment is not None
        assert successor_node.current_assignment.assignment_id == ids.root_assignment_id
        assert successor_node.current_assignment.flow_node_id == ids.root_node_id
        assert refs is not None
        input_text = (tmp_path / "task-recursive-continuation" / refs.input_logical_path).read_text(
            encoding="utf-8"
        )
        assert '"kind": "structural_replan"' in input_text
        assert '"operation": "add_child"' in input_text
        assert (
            tmp_path / "task-recursive-continuation" / "_runtime" / "workflow-manifest.md"
        ).is_file()


async def test_manifest_failure_is_repairable_and_startup_discoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = CapturedRuntimeEffectPublisher()
    async with seeded_executor(
        tmp_path,
        suffix="recursive-repair",
        runtime_effect_publisher=effects,
    ) as (executor, session_factory, ids, _signals):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        signal = effects.signals[0]
        assert isinstance(signal, ReplanCommitted)

        async def fail_projection(*_args: object, **_kwargs: object) -> bool:
            raise OSError("manifest write unavailable")

        monkeypatch.setattr(
            replan_continuation,
            "project_workflow_manifest",
            fail_projection,
        )
        dependencies = _opening_dependencies()
        async with session_factory() as session:
            failed = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=signal.transition_id,
                dependencies=dependencies,
            )
            transition = await session.get(ReplanTransitionModel, signal.transition_id)
            flow = await session.get(FlowModel, ids.flow_id)
        page = await read_replan_continuation_page(
            lambda: cast(
                AbstractAsyncContextManager[AsyncSession],
                session_factory(),
            ),
            cursor=None,
            page_size=10,
        )

        assert failed.outcome == "paused"
        assert transition is not None
        assert transition.manifest_state == "repair_required"
        assert transition.successor_state == "blocked"
        assert flow is not None and flow.current_dispatch_id is None
        assert page.sources == (ReplanCommitted(signal.transition_id),)

        monkeypatch.undo()
        async with session_factory() as session:
            repaired = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=signal.transition_id,
                dependencies=dependencies,
            )
            transition = await session.get(ReplanTransitionModel, signal.transition_id)
        assert repaired.outcome == "opened"
        assert transition is not None and transition.successor_state == "opened"


async def test_concurrent_replans_have_one_winner_and_no_leaked_successors(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-race") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="add_child",
                        arguments={"child": {"title": "Reviewer"}},
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="add_child",
                        arguments={"child": {"title": "Verifier"}},
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code == OperationFailureCode.CONFLICT
        assert error.is_retryable is True
        assert error.suggested_next_step is not None
        assert "Reread" in error.suggested_next_step
        async with session_factory() as session:
            team_revisions = await session.scalar(
                select(func.count()).select_from(TeamRevisionModel)
            )
            flow_revisions = await session.scalar(
                select(func.count()).select_from(FlowRevisionModel)
            )
            members = await session.scalar(select(func.count()).select_from(MemberModel))
            transitions = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)

        assert team_revisions == 2
        assert flow_revisions == 2
        assert members == 3
        assert transitions == 1
        assert task is not None and task.current_team_revision_id != team_revision_id(ids)
        assert flow is not None and flow.active_flow_revision_id != ids.flow_revision_id


async def test_duplicate_replan_delivery_returns_exact_committed_readback(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-replay") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
            provider_start_revision=0,
        )
        arguments = {"child": {"title": "Reviewer"}}
        committed = await executor.execute(
            scope=scope,
            operation_name="add_child",
            arguments=arguments,
        )
        replayed = await executor.execute(
            scope=scope,
            operation_name="add_child",
            arguments=arguments,
        )
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments=arguments,
            )
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                    provider_start_revision=1,
                ),
                operation_name="add_child",
                arguments=arguments,
            )
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=scope,
                operation_name="add_child",
                arguments={"child": {"title": "Different child"}},
            )

        async with session_factory() as session:
            transition_count = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            member_count = await session.scalar(select(func.count()).select_from(MemberModel))
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert replayed == committed
        assert transition_count == 1
        assert member_count == 3
        assert source is not None and source.node_activity_revision == 1


async def test_failure_after_dual_head_claim_rolls_back_every_replan_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-rollback") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):

        def fail_successor_staging(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected successor staging failure")

        monkeypatch.setattr(
            replan_persistence,
            "stage_replan_successor_rows",
            fail_successor_staging,
        )
        with pytest.raises(RuntimeError, match="injected successor staging failure"):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments={"child": {"title": "Reviewer"}},
            )

        async with session_factory() as session:
            task = await session.get(TaskModel, ids.task_id)
            flow = await session.get(FlowModel, ids.flow_id)
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            team_revisions = await session.scalar(
                select(func.count()).select_from(TeamRevisionModel)
            )
            flow_revisions = await session.scalar(
                select(func.count()).select_from(FlowRevisionModel)
            )
            transitions = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )

        assert task is not None
        assert task.current_team_revision_id == team_revision_id(ids)
        assert flow is not None
        assert flow.active_flow_revision_id == ids.flow_revision_id
        assert flow.current_dispatch_id == ids.current_dispatch_id
        assert source is not None and source.status == "open"
        assert team_revisions == 1
        assert flow_revisions == 1
        assert transitions == 0


async def test_replan_and_terminal_checkpoint_have_one_stable_winner(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-checkpoint-race") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    executor.execute(
                        scope=scope,
                        operation_name="add_child",
                        arguments={"child": {"title": "Reviewer"}},
                    ),
                    executor.execute(
                        scope=scope,
                        operation_name="record_checkpoint",
                        arguments={
                            "checkpoint": {
                                "checkpoint_kind": "terminal",
                                "outcome": "blocked",
                                "handoff": {
                                    "summary": "The assignment is blocked.",
                                    "next_step": "Return the exact terminal result.",
                                },
                            }
                        },
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        error = _one_runtime_error(results)
        assert error.code == OperationFailureCode.CONFLICT
        async with session_factory() as session:
            transitions = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            checkpoints = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id)
            )
            source = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert (transitions, checkpoints) in {(1, 0), (0, 1)}
        assert source is not None
        if transitions:
            assert source.closed_reason == "structural_replan"
        else:
            assert source.status == "open"


@pytest.mark.parametrize("control_operation", ("pause", "cancel"))
async def test_flow_control_winner_prevents_replan_successor_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control_operation: str,
) -> None:
    async with seeded_executor(tmp_path, suffix=f"recursive-{control_operation}-race") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):

        async def apply_control_after_admission(_signal: NodeActivitySignal) -> None:
            async with session_factory() as session:
                flow = await session.get(FlowModel, ids.flow_id)
                assert flow is not None
                control = (
                    pause_runtime_flow if control_operation == "pause" else cancel_runtime_flow
                )
                await control(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=flow.control_revision,
                )

        monkeypatch.setattr(
            executor,
            "_publish_activity_signal",
            apply_control_after_admission,
        )
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="add_child",
                arguments={"child": {"title": "Reviewer"}},
            )

        async with session_factory() as session:
            transition_count = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            team_revision_count = await session.scalar(
                select(func.count()).select_from(TeamRevisionModel)
            )
            flow_revision_count = await session.scalar(
                select(func.count()).select_from(FlowRevisionModel)
            )
            flow = await session.get(FlowModel, ids.flow_id)

        assert transition_count == 0
        assert team_revision_count == 1
        assert flow_revision_count == 1
        assert flow is not None
        assert flow.status == ("paused" if control_operation == "pause" else "cancelled")


@pytest.mark.parametrize("control_operation", ("pause", "cancel"))
async def test_replan_winner_rejects_stale_flow_control(
    tmp_path: Path,
    control_operation: str,
) -> None:
    async with seeded_executor(tmp_path, suffix=f"replan-before-{control_operation}") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            source_flow = await session.get(FlowModel, ids.flow_id)
            assert source_flow is not None
            source_control_revision = source_flow.control_revision
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )

        async with session_factory() as session:
            control = pause_runtime_flow if control_operation == "pause" else cancel_runtime_flow
            with pytest.raises(RuntimeOperationError) as stale:
                await control(
                    cast(AsyncSession, session),
                    ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=source_control_revision,
                )
            transition_count = await session.scalar(
                select(func.count()).select_from(ReplanTransitionModel)
            )
            current_flow = await session.get(FlowModel, ids.flow_id)

        assert stale.value.code == OperationFailureCode.STALE_FLOW_REVISION
        assert transition_count == 1
        assert current_flow is not None and current_flow.status == "running"
        assert current_flow.active_flow_revision_id != ids.flow_revision_id


def _one_runtime_error(results: Sequence[object]) -> RuntimeOperationError:
    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeOperationError)
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    return errors[0]


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )

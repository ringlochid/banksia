from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentDecisionModel,
    AssignmentModel,
    AttemptModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    PolicyRevisionModel,
)
from autoclaw.runtime.boundary import open_boundary_successor
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.flow.continuation import continue_paused_flow
from autoclaw.runtime.flow.service import runtime_flow_read
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    BoundaryAccepted,
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


async def test_exact_yield_source_opens_one_child_dispatch_and_duplicate_loses(
    tmp_path: Path,
) -> None:
    start_publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies_with_publisher(start_publisher)
    async with seeded_executor(tmp_path, suffix="boundary-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _stage_yield_decision(session_factory, ids)
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            signal = BoundaryAccepted(ids.current_dispatch_id)
            first = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            duplicate = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=signal,
                dependencies=dependencies,
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            flow = await session.get(FlowModel, ids.flow_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            successor = (
                await session.get(DispatchTurnModel, first.dispatch_id)
                if first.dispatch_id is not None
                else None
            )
            refs = (
                await session.get(DispatchPromptRefsModel, first.dispatch_id)
                if first.dispatch_id is not None
                else None
            )

    assert first.outcome == "opened", flow.pause_details if flow is not None else None
    assert pre_open.current_dispatch is None
    assert pre_open.current_node_key == "child"
    assert pre_open.active_assignment_id == ids.child_assignment_id
    assert pre_open.active_attempt_id == ids.child_attempt_id
    assert duplicate.outcome == "skipped"
    assert dispatch_count == 4
    assert boundary is not None and boundary.successor_dispatch_id == first.dispatch_id
    assert flow is not None and flow.current_dispatch_id == first.dispatch_id
    assert successor is not None
    assert successor.status == "starting"
    assert successor.opened_reason == "boundary"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert successor.assignment_id == ids.child_assignment_id
    assert refs is not None
    input_text = _read_input(tmp_path, "boundary-continuation", refs)
    assert '"kind": "accepted_boundary"' in input_text
    assert f'"source_dispatch_id": "{ids.current_dispatch_id}"' in input_text
    assert '"node_kind": "worker"' in input_text
    assert '"assign_child"' not in input_text
    assert len(start_publisher.signals) == 1
    start_signal = start_publisher.signals[0]
    assert isinstance(start_signal, DispatchStartDue)
    assert start_signal.dispatch_id == successor.dispatch_id
    assert start_signal.provider_start_revision == 0


async def test_failed_boundary_open_retains_exact_operator_continuation(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    async with seeded_executor(tmp_path, suffix="boundary-operator-recovery") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _stage_yield_decision(session_factory, ids)
        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "yield"},
        )
        async with session_factory() as session:
            failed = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(ids.current_dispatch_id),
                dependencies=_disabled_opening_dependencies(),
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )
            flow = await session.get(FlowModel, ids.flow_id)
            assert flow is not None
            expected_control_revision = flow.control_revision

        async with session_factory() as session:
            resumed = await continue_paused_flow(
                cast(AsyncSession, session),
                task_id=ids.task_id,
                expected_active_flow_revision_id=ids.flow_revision_id,
                expected_control_revision=expected_control_revision,
                dependencies=_opening_dependencies_with_publisher(publisher),
            )
            with pytest.raises(RuntimeOperationError) as duplicate_error:
                await continue_paused_flow(
                    cast(AsyncSession, session),
                    task_id=ids.task_id,
                    expected_active_flow_revision_id=ids.flow_revision_id,
                    expected_control_revision=expected_control_revision,
                    dependencies=_opening_dependencies(),
                )
            resumed_boundary = await session.scalar(
                select(AcceptedBoundaryModel)
                .where(AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id)
                .execution_options(populate_existing=True)
            )
            resumed_flow = await session.scalar(
                select(FlowModel)
                .where(FlowModel.flow_id == ids.flow_id)
                .execution_options(populate_existing=True)
            )
            successor = await session.get(DispatchTurnModel, resumed.dispatch_id)

    assert failed.outcome == "paused"
    assert boundary is not None and boundary.successor_dispatch_id is None
    assert flow.status == "paused" and flow.pause_reason == "runtime_transition_failed"
    assert resumed.outcome == "opened"
    assert resumed_boundary is not None
    assert resumed_boundary.successor_dispatch_id == resumed.dispatch_id
    assert resumed_flow is not None and resumed_flow.status == "running"
    assert resumed_flow.current_dispatch_id == resumed.dispatch_id
    assert resumed_flow.control_revision == expected_control_revision + 1
    assert successor is not None and successor.opened_reason == "boundary"
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    assert duplicate_error.value.code == OperationFailureCode.CONFLICT
    assert len(publisher.signals) == 1


@pytest.mark.parametrize(
    ("outcome", "opened_reason", "trigger_kind"),
    (
        ("retry", "semantic_retry", "semantic_retry"),
        ("green", "child_return", "child_return"),
    ),
)
async def test_terminal_worker_boundary_opens_its_exact_routed_target(
    tmp_path: Path,
    outcome: str,
    opened_reason: str,
    trigger_kind: str,
) -> None:
    dependencies = _opening_dependencies()
    async with seeded_executor(tmp_path, suffix=f"boundary-{outcome}-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _make_child_current(session_factory, ids, retry=(outcome == "retry"))
        checkpoint_id = await _record_checkpoint(executor, ids, outcome=outcome)
        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": outcome},
        )

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            result = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(ids.current_dispatch_id),
                dependencies=dependencies,
            )
            successor = (
                await session.get(DispatchTurnModel, result.dispatch_id)
                if result.dispatch_id is not None
                else None
            )
            refs = (
                await session.get(DispatchPromptRefsModel, result.dispatch_id)
                if result.dispatch_id is not None
                else None
            )
            assignment = await session.get(AssignmentModel, ids.child_assignment_id)

    assert result.outcome == "opened"
    assert pre_open.current_dispatch is None
    assert successor is not None and successor.opened_reason == opened_reason
    assert successor.predecessor_dispatch_id == ids.current_dispatch_id
    if outcome == "retry":
        assert assignment is not None
        assert pre_open.current_node_key == "child"
        assert pre_open.active_assignment_id == ids.child_assignment_id
        assert pre_open.active_attempt_id == assignment.current_attempt_id
        assert successor.assignment_id == ids.child_assignment_id
        assert successor.attempt_id == assignment.current_attempt_id
        assert successor.attempt_id != ids.child_attempt_id
    else:
        assert pre_open.current_node_key == "root"
        assert pre_open.active_assignment_id == ids.root_assignment_id
        assert pre_open.active_attempt_id == ids.root_attempt_id
        assert successor.assignment_id == ids.root_assignment_id
        assert successor.attempt_id == ids.root_attempt_id
    assert refs is not None
    request_root = tmp_path / f"task-boundary-{outcome}-continuation"
    input_text = (request_root / refs.input_logical_path).read_text(encoding="utf-8")
    assert f'"kind": "{trigger_kind}"' in input_text
    assert input_text.count(checkpoint_id) == 1


async def test_root_terminal_boundary_has_no_successor_dispatch(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="boundary-root-terminal") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        async with session_factory() as session:
            child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            assert child_attempt is not None
            child_attempt.status = "completed"
            child_attempt.terminal_outcome = "blocked"
            child_attempt.closed_at = utc_now()
            child_attempt.latest_checkpoint_id = ids.child_checkpoint_id
            await session.commit()
        await _record_checkpoint(executor, ids, outcome="blocked")
        await executor.execute(
            scope=_current_scope(ids),
            operation_name="release_blocked",
            arguments={"expected_structural_revision_id": ids.flow_revision_id},
        )
        await executor.execute(
            scope=_current_scope(ids),
            operation_name="return_boundary",
            arguments={"boundary": "blocked"},
        )

        async with session_factory() as session:
            result = await open_boundary_successor(
                cast(AsyncSession, session),
                signal=BoundaryAccepted(ids.current_dispatch_id),
                dependencies=_opening_dependencies(),
            )
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )
            boundary = await session.scalar(
                select(AcceptedBoundaryModel).where(
                    AcceptedBoundaryModel.source_dispatch_id == ids.current_dispatch_id
                )
            )

    assert result.outcome == "terminal"
    assert result.dispatch_id is None
    assert dispatch_count == 3
    assert boundary is not None and boundary.successor_dispatch_id is None


def _opening_dependencies() -> DispatchOpeningDependencies:
    return _opening_dependencies_with_publisher(CapturedRuntimeEffectPublisher())


def _opening_dependencies_with_publisher(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


def _disabled_opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=False),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )


def _read_input(
    tmp_path: Path,
    suffix: str,
    refs: DispatchPromptRefsModel,
) -> str:
    return (tmp_path / f"task-{suffix}" / refs.input_logical_path).read_text(encoding="utf-8")


def _current_scope(ids: RuntimeIds) -> NodeOperationScope:
    return NodeOperationScope(
        task_id=ids.task_id,
        dispatch_id=ids.current_dispatch_id,
    )


async def _stage_yield_decision(
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> None:
    async with session_factory() as session:
        child_node = await session.get(FlowNodeModel, ids.child_node_id)
        child_assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert child_node is not None
        assert child_assignment is not None
        assert child_attempt is not None
        assert policy is not None
        child_node.state = "waiting"
        child_assignment.created_by_dispatch_id = ids.current_dispatch_id
        child_attempt.status = "pending"
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow the target runtime continuation.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        session.add(
            AssignmentDecisionModel(
                assignment_decision_id=f"assignment-decision.{ids.current_dispatch_id}",
                source_dispatch_id=ids.current_dispatch_id,
                task_id=ids.task_id,
                flow_id=ids.flow_id,
                assignment_id=ids.root_assignment_id,
                attempt_id=ids.root_attempt_id,
                source_flow_revision_id=ids.flow_revision_id,
                decision_kind="staged_child",
                staged_child_assignment_id=ids.child_assignment_id,
                staged_child_attempt_id=ids.child_attempt_id,
            )
        )
        await session.commit()


async def _make_child_current(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    *,
    retry: bool,
) -> None:
    async with session_factory() as session:
        dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        root_node = await session.get(FlowNodeModel, ids.root_node_id)
        child_node = await session.get(FlowNodeModel, ids.child_node_id)
        assignment = await session.get(AssignmentModel, ids.child_assignment_id)
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert dispatch is not None
        assert root_node is not None
        assert child_node is not None
        assert assignment is not None
        assert policy is not None
        dispatch.assignment_id = ids.child_assignment_id
        dispatch.attempt_id = ids.child_attempt_id
        dispatch.node_key = "child"
        root_node.state = "waiting"
        child_node.state = "running"
        if retry:
            assignment.retry_limit = 2
            assignment.retries_remaining = 2
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow the target runtime continuation.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        await session.commit()


async def _record_checkpoint(
    executor: NodeOperationExecutor,
    ids: RuntimeIds,
    *,
    outcome: str,
) -> str:
    result = await executor.execute(
        scope=_current_scope(ids),
        operation_name="record_checkpoint",
        arguments={
            "checkpoint": {
                "checkpoint_kind": "terminal",
                "outcome": outcome,
                "handoff": {
                    "summary": f"The worker returned {outcome}.",
                    "next_step": "Open the exact routed continuation.",
                },
            }
        },
    )
    return str(result.model_dump()["checkpoint_id"])


__all__ = []

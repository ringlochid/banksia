from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast

import autoclaw.runtime.node_operations.executor as executor_module
import pytest
from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    DispatchTurnModel,
    FlowNodeModel,
    HumanRequestModel,
    PolicyRevisionModel,
    RoleRevisionModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import (
    read_node_operation_authority,
    refresh_node_activity,
)
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import NodeActivitySignal, NodeOperationScope
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)


async def _seed_definition_lookup_content(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        role_revision = await session.get(
            RoleRevisionModel,
            "role-revision.target.1",
        )
        policy_revision = await session.get(
            PolicyRevisionModel,
            "policy-revision.target.1",
        )
        assert role_revision is not None and policy_revision is not None
        role_revision.content_json = {
            "id": "role.target",
            "description": "Target role.",
            "allowed_node_kinds": ["root", "parent", "worker"],
        }
        policy_revision.content_json = {
            "id": "policy.target",
            "description": "Target policy.",
            "applies_to": ["root", "parent", "worker"],
        }
        await session.commit()


async def test_executor_refreshes_activity_once_and_plan_revisions_only_on_change(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="plan") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        first = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Bound the implementation.",
                "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
            },
        )
        repeated = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Bound the implementation.",
                "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
            },
        )
        cleared = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={"steps": []},
        )
        clear_absent = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={"steps": []},
        )

        assert first.model_dump()["changed"] is True
        assert repeated.model_dump()["changed"] is False
        assert cleared.model_dump() == {"changed": True, "plan": None}
        assert clear_absent.model_dump() == {"changed": False, "plan": None}
        assert [signal.activity_revision for signal in signals] == [1, 2, 3, 4]
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            assignment = await session.get(AssignmentModel, ids.root_assignment_id)
        assert dispatch is not None and dispatch.node_activity_revision == 4
        assert assignment is not None and assignment.work_plan_revision == 2


async def test_pre_admission_scope_failure_does_not_refresh_activity(tmp_path: Path) -> None:
    async with seeded_executor(tmp_path, suffix="stale") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        with pytest.raises(RuntimeOperationError):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id="task.wrong",
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="get_current_context",
                arguments={},
            )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
        assert signals == []
        assert dispatch is not None and dispatch.node_activity_revision == 0


async def test_two_stale_session_admissions_both_advance_activity_monotonically(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="activity-race") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        async with session_factory() as first_session:
            first_authority = await read_node_operation_authority(
                cast(AsyncSession, first_session),
                scope,
            )
        async with session_factory() as second_session:
            second_authority = await read_node_operation_authority(
                cast(AsyncSession, second_session),
                scope,
            )

        later_activity = utc_now() + timedelta(minutes=1)
        async with session_factory() as first_session:
            first_refresh = await refresh_node_activity(
                cast(AsyncSession, first_session),
                first_authority,
                occurred_at=later_activity,
            )
            await first_session.commit()
        async with session_factory() as second_session:
            second_refresh = await refresh_node_activity(
                cast(AsyncSession, second_session),
                second_authority,
                occurred_at=later_activity - timedelta(minutes=2),
            )
            await second_session.commit()
        async with session_factory() as read_session:
            dispatch = await read_session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert first_refresh.activity_revision == 1
        assert second_refresh.activity_revision == 2
        assert second_refresh.occurred_at == first_refresh.occurred_at
        assert dispatch is not None
        assert dispatch.node_activity_revision == 2
        assert dispatch.last_node_activity_at == second_refresh.occurred_at


async def test_executor_publishes_the_committed_activity_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="activity-signal") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        monkeypatch.setattr(
            executor_module,
            "utc_now",
            lambda: utc_now() - timedelta(days=1),
        )

        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert dispatch is not None
        assert len(signals) == 1
        assert signals[0].activity_revision == dispatch.node_activity_revision
        assert signals[0].occurred_at == dispatch.last_node_activity_at


async def test_transaction_b_rechecks_state_changed_after_activity_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="state-race") as (
        executor,
        session_factory,
        ids,
        signals,
    ):

        async def publish_and_record_terminal_checkpoint(signal: NodeActivitySignal) -> None:
            signals.append(signal)
            checkpoint_id = "checkpoint.state-race.terminal"
            async with session_factory() as session:
                attempt = await session.get(AttemptModel, ids.root_attempt_id)
                assert attempt is not None
                session.add(
                    AttemptCheckpointModel(
                        checkpoint_id=checkpoint_id,
                        task_id=ids.task_id,
                        flow_id=ids.flow_id,
                        assignment_id=ids.root_assignment_id,
                        attempt_id=ids.root_attempt_id,
                        authoring_dispatch_id=ids.current_dispatch_id,
                        checkpoint_kind="terminal",
                        outcome="blocked",
                        summary="A concurrent controller transition made waits illegal.",
                        evidence_json={},
                        criteria_results_json=[],
                        recorded_at=utc_now(),
                    )
                )
                attempt.latest_checkpoint_id = checkpoint_id
                await session.commit()

        monkeypatch.setattr(
            executor,
            "_publish_activity_signal",
            publish_and_record_terminal_checkpoint,
        )

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="open_human_request",
                arguments={
                    "request": {
                        "kind": "direction",
                        "summary": "Choose one bounded direction.",
                        "items": [
                            {
                                "id": "direction",
                                "prompt": "Which direction?",
                                "options": [{"id": "a", "title": "A"}],
                            }
                        ],
                    }
                },
            )

        async with session_factory() as session:
            request = await session.scalar(
                select(HumanRequestModel).where(HumanRequestModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)

        assert error.value.code == OperationFailureCode.ILLEGAL_STATE
        assert error.value.is_retryable is False
        assert request is None
        assert dispatch is not None and dispatch.status == "open"
        assert dispatch.node_activity_revision == 1
        assert attempt is not None
        assert attempt.latest_checkpoint_id == "checkpoint.state-race.terminal"
        assert [signal.activity_revision for signal in signals] == [1]


async def test_transaction_b_rejects_rotated_managed_generation_after_activity_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="generation-between-phases") as (
        executor,
        session_factory,
        ids,
        signals,
    ):

        async def publish_and_rotate_generation(signal: NodeActivitySignal) -> None:
            signals.append(signal)
            async with session_factory() as session:
                dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
                assert dispatch is not None
                dispatch.provider_start_revision += 1
                await session.commit()

        monkeypatch.setattr(
            executor,
            "_publish_activity_signal",
            publish_and_rotate_generation,
        )

        with pytest.raises(RuntimeOperationError) as error:
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                    provider_start_revision=0,
                ),
                operation_name="open_human_request",
                arguments={
                    "request": {
                        "kind": "direction",
                        "summary": "Choose one bounded direction.",
                        "items": [
                            {
                                "id": "direction",
                                "prompt": "Which direction?",
                                "options": [{"id": "a", "title": "A"}],
                            }
                        ],
                    }
                },
            )

        async with session_factory() as session:
            request = await session.scalar(
                select(HumanRequestModel).where(HumanRequestModel.task_id == ids.task_id)
            )
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert error.value.code == OperationFailureCode.STALE_DISPATCH
        assert error.value.is_retryable is False
        assert request is None
        assert dispatch is not None
        assert dispatch.status == "open"
        assert dispatch.provider_start_revision == 1
        assert dispatch.node_activity_revision == 1
        assert [signal.activity_revision for signal in signals] == [1]


async def test_definition_search_routes_role_and_policy_without_workflow_fallback(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="definition-search") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        await _seed_definition_lookup_content(session_factory)
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        role_result = await executor.execute(
            scope=scope,
            operation_name="search_definitions",
            arguments={"kind": "role"},
        )
        policy_result = await executor.execute(
            scope=scope,
            operation_name="search_definitions",
            arguments={"kind": "policy"},
        )

        with pytest.raises(ValidationError, match="Input should be"):
            await executor.execute(
                scope=scope,
                operation_name="search_definitions",
                arguments={"kind": "workflow"},
            )

        role_payload = role_result.model_dump(mode="json")
        policy_payload = policy_result.model_dump(mode="json")
        assert role_payload["kind"] == "role"
        assert [item["key"] for item in role_payload["items"]] == ["role.target"]
        assert role_payload["items"][0]["allowed_node_kinds"] == [
            "root",
            "parent",
            "worker",
        ]
        assert role_payload["items"][0]["applies_to"] is None
        assert policy_payload["kind"] == "policy"
        assert [item["key"] for item in policy_payload["items"]] == ["policy.target"]
        assert policy_payload["items"][0]["allowed_node_kinds"] is None
        assert policy_payload["items"][0]["applies_to"] == [
            "root",
            "parent",
            "worker",
        ]
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_definition_get_routes_role_and_policy_without_workflow_fallback(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="definition-get") as (
        executor,
        session_factory,
        ids,
        signals,
    ):
        await _seed_definition_lookup_content(session_factory)
        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        role_detail = await executor.execute(
            scope=scope,
            operation_name="get_definition",
            arguments={"kind": "role", "key": "role.target"},
        )
        policy_detail = await executor.execute(
            scope=scope,
            operation_name="get_definition",
            arguments={"kind": "policy", "key": "policy.target"},
        )

        with pytest.raises(ValidationError, match="Input should be"):
            await executor.execute(
                scope=scope,
                operation_name="get_definition",
                arguments={"kind": "workflow", "key": "workflow.target"},
            )

        role_detail_payload = role_detail.model_dump(mode="json")
        policy_detail_payload = policy_detail.model_dump(mode="json")
        assert role_detail_payload["key"] == "role.target"
        assert role_detail_payload["content"]["allowed_node_kinds"] == [
            "root",
            "parent",
            "worker",
        ]
        assert policy_detail_payload["key"] == "policy.target"
        assert policy_detail_payload["content"]["applies_to"] == [
            "root",
            "parent",
            "worker",
        ]
        assert [signal.activity_revision for signal in signals] == [1, 2]


async def test_assign_child_stages_one_direct_child_without_closing_source(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="assign") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            child = await session.get(FlowNodeModel, ids.child_node_id)
            policy_revision = await session.get(
                PolicyRevisionModel,
                "policy-revision.target.1",
            )
            assert child is not None and policy_revision is not None
            child.current_assignment_id = None
            child.state = "ready"
            policy_revision.content_json = {
                "id": "policy.target",
                "description": "Target policy with a child retry budget.",
                "applies_to": ["root", "parent", "worker"],
                "budget_spec": {"retry_limit": 4},
            }
            await session.commit()

        result = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="assign_child",
            arguments={
                "expected_structural_revision_id": ids.flow_revision_id,
                "payload": {
                    "child_node_key": "child",
                    "assignment_intent": {"summary": "Do bounded child work."},
                },
            },
        )
        async with session_factory() as session:
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            staged_assignment = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.assignment_key == result.model_dump()["target_assignment_key"]
                )
            )
            staged_attempt = await session.get(
                AttemptModel,
                result.model_dump()["target_attempt_id"],
            )
        assert dispatch is not None and dispatch.status == "open"
        assert child is not None and staged_assignment is not None
        assert child.current_assignment_id == staged_assignment.assignment_id
        assert staged_assignment.parent_assignment_id == ids.root_assignment_id
        assert staged_assignment.child_assignment_limit is None
        assert staged_assignment.child_assignments_remaining is None
        assert staged_assignment.retry_limit == 4
        assert staged_assignment.retries_remaining == 4
        assert staged_attempt is not None and staged_attempt.latest_checkpoint_id is None

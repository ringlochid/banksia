from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from autoclaw.definitions.registry import (
    build_role_policy_lookup,
    compile_current_workflow_launch_snapshot,
    load_current_policy,
    load_current_role,
    load_current_workflow,
    upsert_policy_definition,
    upsert_role_definition,
    upsert_workflow_definition,
)
from autoclaw.definitions.registry.task_start import start_task_from_definition
from autoclaw.paths import default_database_path
from autoclaw.persistence import (
    AssignmentModel,
    AttemptModel,
    CompiledPlanNodeModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    PolicyDefinitionModel,
    RoleDefinitionModel,
    TaskEventModel,
    TaskEventStreamHeadModel,
    WorkflowDefinitionModel,
)
from autoclaw.runtime.contracts import TaskEventType, TaskStartRequest
from autoclaw.runtime.ids import flow_id_for_task
from autoclaw.runtime.post_commit import FlowStartCommitted, RuntimeEffectSignal
from autoclaw.runtime.projection import (
    AttemptAssignmentProjection,
    CriteriaProjection,
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from tests.helpers.definition_registry_runtime import initialized_registry


class _CommittedRuntimePublisher:
    def __init__(
        self,
        *,
        session: Any,
        database_path: Path,
        should_accept: bool = True,
        should_raise: bool = False,
    ) -> None:
        self._session = session
        self._database_path = database_path
        self._should_accept = should_accept
        self._should_raise = should_raise
        self.signals: list[RuntimeEffectSignal] = []

    def publish(self, signal: RuntimeEffectSignal) -> bool:
        _assert_launch_source_is_committed(self._session, self._database_path)
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("runtime publication unavailable")
        return self._should_accept


class _CommittedProjectionPublisher:
    def __init__(
        self,
        *,
        session: Any,
        database_path: Path,
        should_accept: bool = True,
        should_raise: bool = False,
    ) -> None:
        self._session = session
        self._database_path = database_path
        self._should_accept = should_accept
        self._should_raise = should_raise
        self.signals: list[SupportProjectionSignal] = []

    def publish(self, signal: SupportProjectionSignal) -> bool:
        _assert_launch_source_is_committed(self._session, self._database_path)
        self.signals.append(signal)
        if self._should_raise:
            raise RuntimeError("projection publication unavailable")
        return self._should_accept


def _assert_launch_source_is_committed(session: Any, database_path: Path) -> None:
    assert not session.in_transaction()
    with sqlite3.connect(database_path) as connection:
        flow_count = connection.execute("SELECT COUNT(*) FROM flows").fetchone()
    assert flow_count == (1,)


def _assert_snapshot_revision_alignment(
    *,
    workflow_definition: WorkflowDefinitionModel,
    role_definition: RoleDefinitionModel,
    policy_definition: PolicyDefinitionModel,
    snapshot: Any,
    lookup: Any,
    workflow_revision_no: int,
    role_revision_no: int,
    policy_revision_no: int,
) -> None:
    assert workflow_definition.current_revision is not None
    assert role_definition.current_revision is not None
    assert policy_definition.current_revision is not None
    assert workflow_definition.current_revision.revision_no == workflow_revision_no
    assert role_definition.current_revision.revision_no == role_revision_no
    assert policy_definition.current_revision.revision_no == policy_revision_no
    assert snapshot.workflow.revision_no == workflow_revision_no
    assert snapshot.compiled_plan.definition_revision_no == workflow_revision_no
    lookup_role = lookup.get_role("planning_lead")
    lookup_policy = lookup.get_policy("standard-parent")
    assert lookup_role is not None
    assert lookup_policy is not None
    assert lookup_role.revision_no == role_revision_no
    assert lookup_policy.revision_no == policy_revision_no
    snapshot_role = snapshot.role_policy_lookup.get_role("planning_lead")
    snapshot_policy = snapshot.role_policy_lookup.get_policy("standard-parent")
    assert snapshot_role is not None
    assert snapshot_policy is not None
    assert snapshot_role.revision_no == role_revision_no
    assert snapshot_policy.revision_no == policy_revision_no


def _assert_snapshot_plan_node_alignment(
    snapshot: Any,
    *,
    role_revision_no: int,
    policy_revision_no: int,
) -> None:
    plan_nodes_by_key = {node.node_key: node for node in snapshot.compiled_plan.nodes}
    implementation_plan_node = plan_nodes_by_key["change_subtree"]
    assert implementation_plan_node.role_revision_no == role_revision_no
    assert implementation_plan_node.policy_revision_no == policy_revision_no
    assert implementation_plan_node.parent_node_key == "root"
    assert "change_subtree" in plan_nodes_by_key["root"].child_node_keys
    assert snapshot.compiled_plan.dependency_edges
    first_plan_edge = snapshot.compiled_plan.dependency_edges[0]
    assert (
        plan_nodes_by_key[first_plan_edge.provider_node_key].node_key
        == first_plan_edge.provider_node_key
    )
    assert (
        plan_nodes_by_key[first_plan_edge.consumer_node_key].node_key
        == first_plan_edge.consumer_node_key
    )


async def test_launch_snapshot_rejects_corrupt_stored_workflow_id(
    tmp_path: Path,
) -> None:
    workflow_key = "corrupt-launch-snapshot-proof"
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            workflow = await load_current_workflow(session, "bounded-change")
            cloned_workflow = workflow.definition.model_copy(update={"id": workflow_key})
            workflow_revision = await upsert_workflow_definition(
                session,
                cloned_workflow,
                source_path="test://corrupt-launch-snapshot-proof",
            )
            await session.commit()
            assert workflow_revision.revision_no == 1

        async with session_factory() as session:
            workflow_definition = await session.scalar(
                select(WorkflowDefinitionModel)
                .options(joinedload(WorkflowDefinitionModel.current_revision))
                .where(WorkflowDefinitionModel.workflow_key == workflow_key)
            )
            assert workflow_definition is not None
            assert workflow_definition.current_revision is not None
            workflow_definition.current_revision.content_json = (
                workflow_definition.current_revision.content_json | {"id": "corrupt-workflow-id"}
            )
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(
                ValueError,
                match=(
                    f"workflow revision metadata key '{workflow_key}' "
                    "does not match workflow id 'corrupt-workflow-id'"
                ),
            ):
                await compile_current_workflow_launch_snapshot(
                    session,
                    workflow_key=workflow_key,
                    compiler_version="registry-key-proof",
                )


async def test_launch_snapshot_ignores_corrupt_unused_current_policy_rows(
    tmp_path: Path,
) -> None:
    unused_policy_key = "unused-review-proof"
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            baseline_policy = await load_current_policy(session, "standard-worker")
            cloned_policy = baseline_policy.definition.model_copy(update={"id": unused_policy_key})
            policy_revision = await upsert_policy_definition(
                session,
                cloned_policy,
                source_path="test://unused-review-proof",
            )
            await session.commit()
            assert policy_revision.revision_no == 1

        async with session_factory() as session:
            policy_definition = await session.scalar(
                select(PolicyDefinitionModel)
                .options(joinedload(PolicyDefinitionModel.current_revision))
                .where(PolicyDefinitionModel.policy_key == unused_policy_key)
            )
            assert policy_definition is not None
            assert policy_definition.current_revision is not None
            policy_definition.current_revision.content_json = {
                "id": unused_policy_key,
                "description": "Corrupt current policy row that should stay unused.",
            }
            await session.commit()

        async with session_factory() as session:
            snapshot = await compile_current_workflow_launch_snapshot(
                session,
                workflow_key="bounded-change",
                compiler_version="referenced-only-proof",
            )

            assert snapshot.compiled_plan.workflow_key == "bounded-change"
            assert snapshot.role_policy_lookup.get_role("planning_lead") is not None
            assert snapshot.role_policy_lookup.get_role("engineer") is not None
            assert snapshot.role_policy_lookup.get_policy("standard-root") is not None
            assert snapshot.role_policy_lookup.get_policy("standard-worker") is not None
            assert snapshot.role_policy_lookup.get_policy(unused_policy_key) is None
            assert {node.policy for node in snapshot.compiled_plan.nodes} == {
                "standard-root",
                "standard-worker",
            }


async def test_launch_snapshot_pins_current_registry_workflow_role_and_policy_revisions(
    tmp_path: Path,
) -> None:
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            role = await load_current_role(session, "planning_lead")
            updated_role = role.definition.model_copy(
                update={"description": f"{role.definition.description} v2"}
            )
            role_revision = await upsert_role_definition(
                session,
                updated_role,
                source_path="test://planning-lead-v2",
            )

            policy = await load_current_policy(session, "standard-parent")
            updated_policy = policy.definition.model_copy(
                update={"description": f"{policy.definition.description} v2"}
            )
            policy_revision = await upsert_policy_definition(
                session,
                updated_policy,
                source_path="test://standard-parent-v2",
            )

            workflow = await load_current_workflow(session, "reviewed-change-release")
            updated_workflow = workflow.definition.model_copy(
                update={"description": f"{workflow.definition.description} v2"}
            )
            workflow_revision = await upsert_workflow_definition(
                session,
                updated_workflow,
                source_path="test://reviewed-change-release-v2",
            )
            await session.commit()

        async with session_factory() as session:
            workflow_definition = await session.scalar(
                select(WorkflowDefinitionModel)
                .options(joinedload(WorkflowDefinitionModel.current_revision))
                .where(WorkflowDefinitionModel.workflow_key == "reviewed-change-release")
            )
            role_definition = await session.scalar(
                select(RoleDefinitionModel)
                .options(joinedload(RoleDefinitionModel.current_revision))
                .where(RoleDefinitionModel.role_key == "planning_lead")
            )
            policy_definition = await session.scalar(
                select(PolicyDefinitionModel)
                .options(joinedload(PolicyDefinitionModel.current_revision))
                .where(PolicyDefinitionModel.policy_key == "standard-parent")
            )
            snapshot = await compile_current_workflow_launch_snapshot(
                session,
                workflow_key="reviewed-change-release",
                compiler_version="registry-pin-proof",
            )
            lookup = await build_role_policy_lookup(session)

            assert workflow_definition is not None
            assert role_definition is not None
            assert policy_definition is not None
            _assert_snapshot_revision_alignment(
                workflow_definition=workflow_definition,
                role_definition=role_definition,
                policy_definition=policy_definition,
                snapshot=snapshot,
                lookup=lookup,
                workflow_revision_no=workflow_revision.revision_no,
                role_revision_no=role_revision.revision_no,
                policy_revision_no=policy_revision.revision_no,
            )
            _assert_snapshot_plan_node_alignment(
                snapshot,
                role_revision_no=role_revision.revision_no,
                policy_revision_no=policy_revision.revision_no,
            )


async def test_task_start_returns_a_logical_unmaterialized_manifest_ref(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "task-data"
    request = TaskStartRequest.model_validate(
        {
            "task": {
                "key": "logical-manifest-ref",
                "title": "Keep task start source-only",
                "summary": "Return the canonical manifest ref without projecting files.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )

    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task_from_definition(
                request,
                data_dir=data_dir,
                session=session,
            )
            dispatch_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(DispatchTurnModel.task_id == response.task_id)
            )
            event_stream_head = await session.get(TaskEventStreamHeadModel, response.task_id)
            task_started = await session.scalar(
                select(TaskEventModel).where(TaskEventModel.task_id == response.task_id)
            )

    assert response.workflow_manifest_ref.path == Path("_runtime/workflow-manifest.md")
    assert dispatch_count == 0
    assert event_stream_head is not None
    assert event_stream_head.allocator_revision == 1
    assert event_stream_head.last_event_seq == 1
    assert event_stream_head.last_event_hash is not None
    assert task_started is not None
    assert task_started.event_type == TaskEventType.TASK_STARTED
    assert not (data_dir / "tasks" / response.task_id).exists()


async def test_task_start_publishes_exact_follow_on_only_after_sqlite_commit(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "task-data"
    request = TaskStartRequest.model_validate(
        {
            "task": {
                "key": "committed-launch-follow-on",
                "title": "Publish committed launch follow-on",
                "summary": "Prove source commit precedes exact runtime and support hints.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )

    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            runtime_publisher = _CommittedRuntimePublisher(
                session=session,
                database_path=default_database_path(tmp_path / "autoclaw-data"),
            )
            projection_publisher = _CommittedProjectionPublisher(
                session=session,
                database_path=default_database_path(tmp_path / "autoclaw-data"),
            )
            response = await start_task_from_definition(
                request,
                data_dir=data_dir,
                session=session,
                runtime_effect_publisher=runtime_publisher,
                support_projection_publisher=projection_publisher,
            )

    assert runtime_publisher.signals == [FlowStartCommitted(flow_id_for_task(response.task_id))]
    assert isinstance(projection_publisher.signals[0], WorkflowManifestProjection)
    assert isinstance(projection_publisher.signals[-1], AttemptAssignmentProjection)
    assert any(isinstance(signal, CriteriaProjection) for signal in projection_publisher.signals)
    assert {type(signal) for signal in projection_publisher.signals} == {
        WorkflowManifestProjection,
        CriteriaProjection,
        AttemptAssignmentProjection,
    }


async def test_task_start_response_survives_rejected_and_failed_publication(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "task-data"
    request = TaskStartRequest.model_validate(
        {
            "task": {
                "key": "isolated-launch-publication",
                "title": "Isolate committed launch response",
                "summary": "Keep committed task start independent from disposable hints.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )

    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            runtime_publisher = _CommittedRuntimePublisher(
                session=session,
                database_path=default_database_path(tmp_path / "autoclaw-data"),
                should_accept=False,
            )
            projection_publisher = _CommittedProjectionPublisher(
                session=session,
                database_path=default_database_path(tmp_path / "autoclaw-data"),
                should_raise=True,
            )
            response = await start_task_from_definition(
                request,
                data_dir=data_dir,
                session=session,
                runtime_effect_publisher=runtime_publisher,
                support_projection_publisher=projection_publisher,
            )
            persisted_flow_id = await session.scalar(
                select(FlowModel.flow_id).where(FlowModel.task_id == response.task_id)
            )

    assert persisted_flow_id == flow_id_for_task(response.task_id)
    assert runtime_publisher.signals == [FlowStartCommitted(flow_id_for_task(response.task_id))]
    assert projection_publisher.signals


async def test_task_start_derives_runtime_identity_from_a_nonliteral_root_key(
    tmp_path: Path,
) -> None:
    workflow_key = "nonliteral-root-launch"
    data_dir = tmp_path / "task-data"
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            baseline = await load_current_workflow(session, "bounded-change")
            root = baseline.definition.root.model_copy(update={"node_key": "primary"})
            definition = baseline.definition.model_copy(update={"id": workflow_key, "root": root})
            await upsert_workflow_definition(
                session,
                definition,
                source_path="test://nonliteral-root-launch",
            )
            await session.commit()

        async with session_factory() as session:
            response = await start_task_from_definition(
                TaskStartRequest.model_validate(
                    {
                        "task": {
                            "key": "nonliteral-root",
                            "title": "Launch a nonliteral root",
                            "summary": "Derive runtime identity from authored root truth.",
                        },
                        "workflow": {"key": workflow_key},
                    }
                ),
                data_dir=data_dir,
                session=session,
            )
            assignment = await session.scalar(
                select(AssignmentModel).where(AssignmentModel.task_id == response.task_id)
            )
            attempt = await session.scalar(
                select(AttemptModel).where(AttemptModel.task_id == response.task_id)
            )
            compiled_root = await session.scalar(
                select(CompiledPlanNodeModel).where(
                    CompiledPlanNodeModel.compiled_plan_id == response.compiled_plan_id,
                    CompiledPlanNodeModel.structural_kind == "root",
                )
            )
            flow_root = await session.scalar(
                select(FlowNodeModel).where(
                    FlowNodeModel.flow_revision_id == response.active_flow_revision_id,
                    FlowNodeModel.structural_kind == "root",
                )
            )

    assert assignment is not None
    assert assignment.node_key == "primary"
    assert assignment.assignment_key == f"{response.task_id}.primary.assign-01"
    assert attempt is not None
    assert attempt.node_key == "primary"
    assert attempt.attempt_id == f"attempt.{response.task_id}.primary.01"
    assert compiled_root is not None and compiled_root.node_key == "primary"
    assert flow_root is not None and flow_root.node_key == "primary"

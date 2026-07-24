from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from sqlalchemy import select

from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AssignmentModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    TaskModel,
)
from banksia.providers import ProviderKind
from banksia.runtime import RuntimeLaunchInput
from banksia.runtime.contracts import AssignmentBody
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.launch.continuation import open_root_dispatch
from banksia.runtime.launch.service import launch_task_runtime
from banksia.runtime.node_mcp import DispatchMcpBindingRegistry
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationName
from banksia.runtime.node_operations.catalog import get_node_operation_descriptor
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    DispatchStartDue,
    TaskStartCommitted,
)
from banksia.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStopOutcome,
)
from banksia.runtime.providers.starter import DispatchStarter
from banksia.workflows.catalog import read_current_published_workflow
from tests.helpers.workflow_runtime import initialized_workflow_database


class _AcceptedCodexAdapter:
    kind = ProviderKind.CODEX

    def __init__(self) -> None:
        self.requests: list[DispatchStartRequest] = []

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        self.requests.append(request)
        return ProviderStartAccepted()

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        del dispatch_id
        return ProviderStopOutcome.NOT_RUNNING

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="e2e_available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield


class _OperationLister:
    async def list_operations(self, scope: object) -> tuple[object, ...]:
        del scope
        return (get_node_operation_descriptor(NodeOperationName.GET_CURRENT_CONTEXT),)


class _CapturedScheduler:
    def __init__(self) -> None:
        self.signals: list[DispatchStartDue] = []

    def register(self, signal: DispatchStartDue) -> bool:
        self.signals.append(signal)
        return True


async def test_published_workflow_materializes_exact_team_and_starts_provider(
    tmp_path: Path,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    adapter = _AcceptedCodexAdapter()
    binding_registry = DispatchMcpBindingRegistry()

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            workflow_revision = await read_current_published_workflow(
                session,
                workflow_id="reviewed-delivery",
            )
            await launch_task_runtime(
                session,
                RuntimeLaunchInput(
                    task_id="task.published-workflow-start",
                    task_root=tmp_path / "task.published-workflow-start",
                    workspace=tmp_path,
                    workflow_revision=workflow_revision,
                    assignment=AssignmentBody(
                        prompt="Prove exact Team and provider start truth.",
                    ),
                ),
            )
            await session.commit()
            task = await session.scalar(
                select(TaskModel).where(TaskModel.task_id == "task.published-workflow-start")
            )
            assert task is not None
            opened = await open_root_dispatch(
                session,
                signal=TaskStartCommitted(task.task_id),
                dependencies=_opening_dependencies(publisher),
            )
            assert opened.dispatch_id is not None
            dispatch_id = opened.dispatch_id

        start_signal = next(
            signal for signal in publisher.signals if isinstance(signal, DispatchStartDue)
        )
        scheduler = _CapturedScheduler()
        starter = DispatchStarter(
            adapters=ProviderAdapterRegistry((adapter,)),
            binding_registry=binding_registry,
            operation_executor=cast(NodeOperationExecutor, _OperationLister()),
            scheduler=cast(DeadlineScheduler, scheduler),
            runtime_effect_publisher=publisher,
            runtime_settings=RuntimeSettings(),
            session_factory=session_factory,
            managed_node_mcp_url="http://127.0.0.1:18125/_internal/node/mcp",
            compatibility_node_mcp_url="http://127.0.0.1:18125/node/mcp",
        )
        async with session_factory() as session:
            await starter.schedule_or_start_dispatch(session, start_signal)
        async with session_factory() as session:
            task = await session.get(TaskModel, "task.published-workflow-start")
            assignment = await session.scalar(
                select(AssignmentModel).where(
                    AssignmentModel.task_id == "task.published-workflow-start",
                    AssignmentModel.member_id == "lead",
                )
            )
            dispatch = await session.get(DispatchTurnModel, dispatch_id)
            capabilities = await session.get(
                DispatchCapabilitySetModel,
                dispatch_id,
            )

    _assert_exact_runtime_truth(task, assignment, dispatch, capabilities)
    _assert_provider_acceptance(
        adapter,
        binding_registry,
        scheduler,
        dispatch_id=dispatch_id,
    )


def _assert_exact_runtime_truth(
    task: TaskModel | None,
    assignment: AssignmentModel | None,
    dispatch: DispatchTurnModel | None,
    capabilities: DispatchCapabilitySetModel | None,
) -> None:
    assert task is not None and task.current_team_revision_id is not None
    assert task.workflow_key == "reviewed-delivery" and task.workflow_revision_no == 1
    assert task.max_wave_members == 8
    assert assignment is not None
    assert assignment.member_id == "lead"
    assert assignment.child_assignment_limit == 20 and assignment.retry_limit == 1
    assert dispatch is not None and dispatch.status == "open"
    assert dispatch.team_revision_id == task.current_team_revision_id
    assert dispatch.member_id == assignment.member_id
    assert dispatch.member_configuration_id
    assert dispatch.member_branch_basis_id
    assert dispatch.requested_provider == dispatch.resolved_provider == "codex"
    assert dispatch.provider_selection_basis == "default"
    assert capabilities is not None
    assert capabilities.requested_human_direction == "deny"
    assert capabilities.human_direction == "deny"
    assert capabilities.requested_command_run == "deny"
    assert capabilities.command_run == "deny"


def _assert_provider_acceptance(
    adapter: _AcceptedCodexAdapter,
    binding_registry: DispatchMcpBindingRegistry,
    scheduler: _CapturedScheduler,
    *,
    dispatch_id: str,
) -> None:
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.dispatch_id == dispatch_id
    assert request.provider_route.kind is ProviderKind.CODEX
    assert request.instructions and request.input
    assert request.managed_node_mcp is not None
    assert request.managed_node_mcp.enabled_tools == ("get_current_context",)
    assert (
        binding_registry.authenticate(request.managed_node_mcp.bearer_token.get_secret_value())
        is not None
    )
    assert scheduler.signals == []


def _opening_dependencies(
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

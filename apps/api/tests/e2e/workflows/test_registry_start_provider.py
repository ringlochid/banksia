from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.definitions.registry import load_current_workflow, upsert_workflow_definition
from autoclaw.definitions.registry.task_start import start_task_from_definition
from autoclaw.persistence.models import CompiledPlanModel, DispatchTurnModel
from autoclaw.runtime.contracts import TaskStartRequest
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.launch.continuation import open_root_dispatch
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationName
from autoclaw.runtime.node_operations.catalog import get_node_operation_descriptor
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DeadlineScheduler,
    DispatchStartDue,
    FlowStartCommitted,
)
from autoclaw.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderStopOutcome,
)
from autoclaw.runtime.providers.starter import DispatchStarter
from tests.helpers.definition_registry_runtime import initialized_registry


class _AcceptedProviderAdapter:
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


async def test_registry_snapshot_opens_and_starts_one_committed_provider_dispatch(
    tmp_path: Path,
) -> None:
    runtime_publisher = CapturedRuntimeEffectPublisher()
    adapter = _AcceptedProviderAdapter()
    binding_registry = DispatchMcpBindingRegistry()
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            revision_two = await upsert_workflow_definition(
                session,
                current.definition.model_copy(
                    update={"description": f"{current.definition.description} release proof"}
                ),
                source_path="test://registry-start-provider/revision-2",
            )
            await session.commit()

            started = await start_task_from_definition(
                _start_request(),
                data_dir=tmp_path / "autoclaw-data",
                session=session,
                runtime_effect_publisher=runtime_publisher,
            )
            later = await load_current_workflow(session, "bounded-change")
            await upsert_workflow_definition(
                session,
                later.definition.model_copy(
                    update={"description": f"{later.definition.description} later revision"}
                ),
                source_path="test://registry-start-provider/revision-3",
            )
            await session.commit()

            flow_signal = next(
                signal
                for signal in runtime_publisher.signals
                if isinstance(signal, FlowStartCommitted)
            )
            opened = await open_root_dispatch(
                session,
                signal=flow_signal,
                dependencies=_opening_dependencies(runtime_publisher),
            )
            assert opened.dispatch_id is not None
            dispatch = await session.get(DispatchTurnModel, opened.dispatch_id)
            plan = await session.get(CompiledPlanModel, started.compiled_plan_id)

        start_signal = next(
            signal for signal in runtime_publisher.signals if isinstance(signal, DispatchStartDue)
        )
        scheduler = _CapturedScheduler()
        starter = DispatchStarter(
            adapters=ProviderAdapterRegistry((adapter,)),
            binding_registry=binding_registry,
            operation_executor=cast(NodeOperationExecutor, _OperationLister()),
            scheduler=cast(DeadlineScheduler, scheduler),
            runtime_effect_publisher=runtime_publisher,
            runtime_settings=RuntimeSettings(),
            session_factory=session_factory,
            managed_node_mcp_url="http://127.0.0.1:18125/_internal/node/mcp",
            compatibility_node_mcp_url="http://127.0.0.1:18125/node/mcp",
        )
        async with session_factory() as session:
            await starter.schedule_or_start_dispatch(session, start_signal)
        async with session_factory() as session:
            accepted = await session.get(DispatchTurnModel, opened.dispatch_id)

    assert revision_two.revision_no == 2
    assert plan is not None and plan.definition_revision_no == 2
    assert dispatch is not None and dispatch.status == "starting"
    assert accepted is not None and accepted.status == "open"
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.dispatch_id == opened.dispatch_id
    assert request.instructions
    assert request.input
    assert request.managed_node_mcp is not None
    assert request.managed_node_mcp.enabled_tools == ("get_current_context",)
    assert (
        binding_registry.authenticate(request.managed_node_mcp.bearer_token.get_secret_value())
        is not None
    )
    assert scheduler.signals == []


def _start_request() -> TaskStartRequest:
    return TaskStartRequest.model_validate(
        {
            "task": {
                "key": "registry-start-provider",
                "title": "Registry start provider",
                "summary": "Prove pinned registry truth through provider acceptance.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )


def _opening_dependencies(
    publisher: CapturedRuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            data_dir=Path("/tmp/autoclaw-e2e-data"),
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )

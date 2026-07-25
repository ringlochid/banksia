from __future__ import annotations

from pathlib import Path

import pytest

from banksia.operator.contracts import (
    OperatorActionProposalEntry,
    OperatorMessageRequest,
    OperatorProviderMessageResult,
)
from banksia.operator.operations import (
    OPERATOR_OPERATION_BY_NAME,
    BanksiaOperatorProductOperations,
    OperatorOperationExecutor,
    OperatorOperationName,
    OperatorOperationScope,
)
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import create_operator_services
from banksia.runtime.product.tasks import read_product_task
from banksia.workflows.authoring import open_workflow_draft, read_workflow_draft
from banksia.workflows.authoring_contracts import CreateWorkflowDraftRequest
from tests.helpers.executor_harness import seeded_async_executor
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import initialized_workflow_database

_PROPOSAL_OPERATIONS: tuple[OperatorOperationName, ...] = (
    "workflow_draft_undo",
    "workflow_draft_discard",
    "workflow_draft_publish",
    "task_start",
    "task_control",
    "human_request_respond",
    "command_run_cancel",
)


class ScopeCaptureRunner:
    availability = OperatorProviderAvailability(
        availability="available",
        configured_provider="test",
        problem_code=None,
        explanation="The hermetic Operator provider is available.",
        setup_action=None,
        resolved_model="test-model",
        resolved_effort="high",
    )

    def __init__(self) -> None:
        self.scope: OperatorOperationScope | None = None

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        del operations
        self.scope = OperatorOperationScope(
            conversation_id=invocation.conversation_id,
            invocation_id=invocation.invocation_id,
            claim_generation=invocation.claim_generation,
        )
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The provider turn is complete.",
            ),
            provider_thread_id="scope-thread",
        )


class TaskControlProposalRunner:
    availability = ScopeCaptureRunner.availability

    def __init__(self, *, task_id: str, action_id: str) -> None:
        self._task_id = task_id
        self._action_id = action_id

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        proposal = await operations.execute(
            scope=OperatorOperationScope(
                conversation_id=invocation.conversation_id,
                invocation_id=invocation.invocation_id,
                claim_generation=invocation.claim_generation,
            ),
            provider_call_id="exact-pause-proposal",
            operation_name="task_control",
            arguments={
                "task_id": self._task_id,
                "action_id": self._action_id,
            },
        )
        assert proposal.kind == "proposal"
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The exact pause proposal is ready.",
            ),
            provider_thread_id="task-control-copy-thread",
        )


async def test_all_proposal_product_operations_reject_direct_unconfirmed_calls(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        dependencies = product_dispatch_dependencies(tmp_path)
        product = BanksiaOperatorProductOperations(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
        )
        async with session_factory() as session:
            opened = await open_workflow_draft(
                session,
                request=CreateWorkflowDraftRequest(
                    kind="create",
                    workflow_id="unconfirmed-guard",
                    description="This draft must survive direct calls.",
                ),
            )
            await session.commit()

        arguments: dict[OperatorOperationName, object] = {
            "workflow_draft_undo": {
                "draft_id": opened.draft.draft_id,
                "etag": opened.draft.etag,
                "receipt_id": "receipt-never-used",
            },
            "workflow_draft_discard": {
                "draft_id": opened.draft.draft_id,
                "etag": opened.draft.etag,
            },
            "workflow_draft_publish": {
                "draft_id": opened.draft.draft_id,
                "etag": opened.draft.etag,
            },
            "task_start": {
                "workflow": "reviewed-delivery",
                "prompt": "This must not start without confirmation.",
            },
            "task_control": {"task_id": "task-missing", "action_id": "action-missing"},
            "human_request_respond": {
                "task_id": "task-missing",
                "request_id": "request-missing",
                "action_id": "action-missing",
                "input": {"kind": "cancel"},
            },
            "command_run_cancel": {
                "task_id": "task-missing",
                "command_id": "command-missing",
                "action_id": "action-missing",
            },
        }
        for operation in _PROPOSAL_OPERATIONS:
            spec = OPERATOR_OPERATION_BY_NAME[operation]
            request = spec.request_model.model_validate(arguments[operation])
            with pytest.raises(
                ValueError,
                match="requires confirmation",
            ):
                await product.execute(operation, request)

        async with session_factory() as session:
            retained = await read_workflow_draft(
                session,
                draft_id=opened.draft.draft_id,
            )

    assert retained.etag == opened.draft.etag


async def test_completed_invocation_scope_cannot_execute_even_a_read_operation(
    tmp_path: Path,
) -> None:
    runner = ScopeCaptureRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        dependencies = product_dispatch_dependencies(tmp_path)
        services = create_operator_services(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
            provider_runner=runner,
        )
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Capture this exact invocation."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            assert runner.scope is not None
            result = await services.operations.execute(
                scope=runner.scope,
                provider_call_id="stale-read",
                operation_name="workflow_search",
                arguments={},
            )

    assert result.kind == "failure"
    assert result.problem == "operator_operation_failed"


async def test_task_control_proposal_names_the_exact_human_action_without_internal_ids(
    tmp_path: Path,
) -> None:
    async with seeded_async_executor(tmp_path, suffix="operator-task-control-copy") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            task = await read_product_task(session, ids.task_id)
        pause_action = next(action for action in task.actions if action.kind == "pause")
        runner = TaskControlProposalRunner(
            task_id=ids.task_id,
            action_id=pause_action.id,
        )
        dependencies = product_dispatch_dependencies(tmp_path)
        services = create_operator_services(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
            provider_runner=runner,
        )
        async with services.coordinator:
            created = await services.conversations.create_conversation(
                idempotency_key="create-task-control-copy"
            )
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Pause this run."),
                idempotency_key="message-task-control-copy",
            )
            await services.coordinator.drain()
            current = await services.conversations.read_conversation(created.id)

    proposal = next(
        entry for entry in current.entries if isinstance(entry, OperatorActionProposalEntry)
    )
    assert proposal.label == "Pause run"
    assert "stop opening new work" in proposal.consequence
    assert task.prompt_excerpt in proposal.scope
    rendered = f"{proposal.label} {proposal.scope} {proposal.consequence}"
    assert ids.task_id not in rendered
    assert pause_action.id not in rendered
    assert "pause, resume, or cancel" not in rendered.casefold()
    assert "etag" not in rendered.casefold()

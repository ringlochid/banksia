from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.contracts import (
    OperatorEffectReceiptEntry,
    OperatorMessageRequest,
    OperatorProviderMessageResult,
)
from banksia.operator.errors import OperatorServiceError
from banksia.operator.operations import (
    OperatorOperationExecutor,
    OperatorOperationName,
    OperatorOperationScope,
)
from banksia.operator.operations.executor import OperatorToolResult
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from banksia.operator.storage import OperatorSessionFactory
from banksia.persistence.models import OperatorEffectModel, TaskModel
from banksia.workflows import UpdateWorkflowOperation, WorkflowPatch
from banksia.workflows.authoring import (
    edit_workflow_draft,
    open_workflow_draft,
    publish_workflow_draft,
    read_workflow_draft,
)
from banksia.workflows.authoring_contracts import OpenWorkflowDraftRequest
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import (
    AsyncSessionFactory,
    initialized_workflow_database,
)

_AVAILABLE = OperatorProviderAvailability(
    availability="available",
    configured_provider="test",
    problem_code=None,
    explanation="The hermetic Operator provider is available.",
    setup_action=None,
    resolved_model="test-model",
    resolved_effort="high",
)


class DraftEditOperatorRunner:
    availability = _AVAILABLE

    def __init__(self) -> None:
        self.create_result: OperatorToolResult | None = None
        self.edit_result: OperatorToolResult | None = None

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        scope = OperatorOperationScope(
            conversation_id=invocation.conversation_id,
            invocation_id=invocation.invocation_id,
            claim_generation=invocation.claim_generation,
        )
        self.create_result = await operations.execute(
            scope=scope,
            provider_call_id="call-create",
            operation_name="workflow_draft_create",
            arguments={
                "request": {
                    "kind": "create",
                    "workflow_id": "operator-undo-draft",
                    "description": "Description before the Operator edit.",
                }
            },
        )
        if self.create_result.kind != "result" or self.create_result.result is None:
            raise RuntimeError("draft creation did not return its controller result")
        draft = cast(dict[str, object], self.create_result.result["draft"])
        self.edit_result = await operations.execute(
            scope=scope,
            provider_call_id="call-edit",
            operation_name="workflow_draft_edit",
            arguments={
                "draft_id": draft["draft_id"],
                "etag": draft["etag"],
                "operation": {
                    "kind": "update_workflow",
                    "patch": {"description": "Description after the Operator edit."},
                },
            },
        )
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The draft edit is ready and can be undone.",
            ),
            provider_thread_id=invocation.provider_thread_id or "draft-thread",
        )


class TaskStartProposalRunner:
    availability = _AVAILABLE

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
            provider_call_id="call-task-start",
            operation_name="task_start",
            arguments={
                "workflow": "reviewed-delivery",
                "prompt": "Start only after the exact Workflow revision is confirmed.",
            },
        )
        if proposal.kind != "proposal":
            raise RuntimeError("task start did not produce a confirmation proposal")
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The exact run-start proposal is ready.",
            ),
            provider_thread_id=invocation.provider_thread_id or "task-start-thread",
        )


class InvalidProposalRunner:
    availability = _AVAILABLE

    def __init__(self) -> None:
        self.task_start_result: OperatorToolResult | None = None
        self.undo_result: OperatorToolResult | None = None

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        scope = OperatorOperationScope(
            conversation_id=invocation.conversation_id,
            invocation_id=invocation.invocation_id,
            claim_generation=invocation.claim_generation,
        )
        created = await operations.execute(
            scope=scope,
            provider_call_id="create-draft-only-workflow",
            operation_name="workflow_draft_create",
            arguments={
                "request": {
                    "kind": "create",
                    "workflow_id": "draft-only-proposal",
                    "description": "A Workflow that has not been published.",
                }
            },
        )
        assert created.kind == "result"
        draft = cast(dict[str, object], created.result["draft"])
        self.task_start_result = await operations.execute(
            scope=scope,
            provider_call_id="start-draft-only-workflow",
            operation_name="task_start",
            arguments={
                "workflow": "draft-only-proposal",
                "prompt": "This must not become a proposal.",
            },
        )
        self.undo_result = await operations.execute(
            scope=scope,
            provider_call_id="use-invented-undo-receipt",
            operation_name="workflow_draft_undo",
            arguments={
                "draft_id": draft["draft_id"],
                "etag": draft["etag"],
                "receipt_id": "receipt-invented-by-provider",
            },
        )
        return OperatorProviderOutcome(
            result=OperatorProviderMessageResult(
                kind="message",
                text="The invalid requests were rejected.",
            ),
            provider_thread_id="invalid-proposal-thread",
        )


class SessionFactoryProbe:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory
        self.active_count = 0
        self.maximum_active_count = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.active_count += 1
        self.maximum_active_count = max(self.maximum_active_count, self.active_count)
        try:
            async with self._session_factory() as session:
                yield session
        finally:
            self.active_count -= 1

    def reset(self) -> None:
        self.maximum_active_count = self.active_count


async def test_controller_issued_undo_is_confirmed_once_and_replays_safely(
    tmp_path: Path,
) -> None:
    runner = DraftEditOperatorRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Create and edit a Workflow draft."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            edited_view = await services.conversations.read_conversation(created.id)
            edit_receipt = next(
                entry
                for entry in edited_view.entries
                if isinstance(entry, OperatorEffectReceiptEntry) and entry.undo is not None
            )
            assert edit_receipt.undo is not None
            confirmed = await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=edit_receipt.undo.confirmation_id,
                idempotency_key="confirm-undo",
            )
            replayed = await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=edit_receipt.undo.confirmation_id,
                idempotency_key="confirm-undo",
            )
            with pytest.raises(OperatorServiceError) as reused:
                await services.conversations.confirm_effect(
                    conversation_id=created.id,
                    confirmation_id=edit_receipt.undo.confirmation_id,
                    idempotency_key="different-key",
                )

        assert runner.create_result is not None
        assert runner.create_result.kind == "result"
        assert runner.create_result.result is not None
        draft_payload = cast(dict[str, object], runner.create_result.result["draft"])
        async with session_factory() as session:
            draft = await read_workflow_draft(
                session,
                draft_id=cast(str, draft_payload["draft_id"]),
            )

    assert runner.edit_result is not None and runner.edit_result.kind == "result"
    assert confirmed.entries[-1].kind == "effect_receipt"
    assert replayed.entries == confirmed.entries
    assert reused.value.response.problem.code == "operator_action_not_current"
    assert draft.workflow.description == "Description before the Operator edit."


async def test_confirmation_expires_when_its_task_start_guard_changes(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        probed_session_factory = SessionFactoryProbe(session_factory)
        services = _services(tmp_path, probed_session_factory, TaskStartProposalRunner())
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Prepare the reviewed run."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            proposed = await services.conversations.read_conversation(created.id)
            confirmation = next(
                action for action in proposed.legal_actions if action.kind == "confirm_effect"
            )
            assert confirmation.confirmation_id is not None

            async with session_factory() as session:
                opened = await open_workflow_draft(
                    session,
                    request=OpenWorkflowDraftRequest(
                        kind="open",
                        workflow_id="reviewed-delivery",
                    ),
                )
                edited = await edit_workflow_draft(
                    session,
                    draft_id=opened.draft.draft_id,
                    expected_etag=opened.draft.etag,
                    operation=UpdateWorkflowOperation(
                        kind="update_workflow",
                        patch=WorkflowPatch(
                            description="A newly published revision invalidates the proposal."
                        ),
                    ),
                )
                await publish_workflow_draft(
                    session,
                    draft_id=edited.draft.draft_id,
                    expected_etag=edited.draft.etag,
                )
                await session.commit()

            probed_session_factory.reset()
            filtered = await services.conversations.read_conversation(created.id)
            with pytest.raises(OperatorServiceError) as expired:
                await services.conversations.confirm_effect(
                    conversation_id=created.id,
                    confirmation_id=confirmation.confirmation_id,
                    idempotency_key="confirm-stale",
                )
            current = await services.conversations.read_conversation(created.id)

        async with session_factory() as session:
            effect = await session.scalar(
                select(OperatorEffectModel).where(
                    OperatorEffectModel.confirmation_id == confirmation.confirmation_id
                )
            )

    assert expired.value.response.problem.code == "operator_action_not_current"
    assert [action.kind for action in filtered.legal_actions] == ["send_message"]
    assert probed_session_factory.maximum_active_count == 1
    assert [action.kind for action in current.legal_actions] == ["send_message"]
    assert effect is not None
    assert effect.state == "failed"
    assert effect.confirmation_state == "expired"


async def test_task_start_rechecks_confirmed_revision_inside_admission_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, TaskStartProposalRunner())
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(text="Prepare the exact reviewed run."),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            proposed = await services.conversations.read_conversation(created.id)
            confirmation = next(
                action for action in proposed.legal_actions if action.kind == "confirm_effect"
            )

            original_execute_confirmed = services.operations.execute_confirmed

            async def publish_between_guard_and_task_admission(
                operation: OperatorOperationName,
                request: BaseModel,
                guard: str | None,
            ) -> dict[str, object]:
                async with session_factory() as session:
                    opened = await open_workflow_draft(
                        session,
                        request=OpenWorkflowDraftRequest(
                            kind="open",
                            workflow_id="reviewed-delivery",
                        ),
                    )
                    edited = await edit_workflow_draft(
                        session,
                        draft_id=opened.draft.draft_id,
                        expected_etag=opened.draft.etag,
                        operation=UpdateWorkflowOperation(
                            kind="update_workflow",
                            patch=WorkflowPatch(
                                description="Published after confirmation was claimed."
                            ),
                        ),
                    )
                    await publish_workflow_draft(
                        session,
                        draft_id=edited.draft.draft_id,
                        expected_etag=edited.draft.etag,
                    )
                    await session.commit()
                return await original_execute_confirmed(operation, request, guard)

            monkeypatch.setattr(
                services.operations,
                "execute_confirmed",
                publish_between_guard_and_task_admission,
            )
            confirmed = await services.conversations.confirm_effect(
                conversation_id=created.id,
                confirmation_id=confirmation.confirmation_id,
                idempotency_key="confirm",
            )

        async with session_factory() as session:
            task_count = await session.scalar(select(func.count()).select_from(TaskModel))
            effect = await session.scalar(
                select(OperatorEffectModel).where(
                    OperatorEffectModel.confirmation_id == confirmation.confirmation_id
                )
            )

    assert task_count == 0
    assert effect is not None and effect.state == "failed"
    assert confirmed.entries[-1].kind == "effect_receipt"
    assert confirmed.entries[-1].summary == "Banksia could not apply the requested action."


async def test_invalid_guarded_operations_never_become_proposals(
    tmp_path: Path,
) -> None:
    runner = InvalidProposalRunner()
    async with initialized_workflow_database(tmp_path) as session_factory:
        services = _services(tmp_path, session_factory, runner)
        async with services.coordinator:
            created = await services.conversations.create_conversation(idempotency_key="create")
            await services.conversations.submit_message(
                conversation_id=created.id,
                request=OperatorMessageRequest(
                    text="Try to start a draft and use an invented Undo receipt."
                ),
                idempotency_key="message",
            )
            await services.coordinator.drain()
            current = await services.conversations.read_conversation(created.id)

        async with session_factory() as session:
            proposed_count = await session.scalar(
                select(func.count())
                .select_from(OperatorEffectModel)
                .where(
                    OperatorEffectModel.conversation_id == created.id,
                    OperatorEffectModel.state == "proposed",
                )
            )

    assert runner.task_start_result is not None
    assert runner.task_start_result.kind == "failure"
    assert runner.undo_result is not None
    assert runner.undo_result.kind == "failure"
    assert proposed_count == 0
    assert [action.kind for action in current.legal_actions] == ["send_message"]


def _services(
    tmp_path: Path,
    session_factory: OperatorSessionFactory,
    runner: DraftEditOperatorRunner | TaskStartProposalRunner | InvalidProposalRunner,
) -> OperatorServices:
    dependencies = product_dispatch_dependencies(tmp_path)
    return create_operator_services(
        session_factory=session_factory,
        settings=dependencies.settings,
        dispatch_dependencies=dependencies,
        runtime_effect_publisher=None,
        provider_runner=runner,
    )

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.operations.catalog import OperatorOperationName
from banksia.operator.operations.contracts import (
    CommandRunCancelOperationRequest,
    HumanRequestRespondOperationRequest,
    OperatorHumanAnswerInput,
    TaskControlOperationRequest,
    TaskStartOperationRequest,
    WorkflowDraftDiscardOperationRequest,
    WorkflowDraftPublishOperationRequest,
    WorkflowDraftUndoOperationRequest,
)
from banksia.operator.operations.descriptions import (
    describe_command_cancel,
    describe_draft_discard,
    describe_draft_publish,
    describe_draft_undo,
    describe_human_response,
    describe_task_control,
    describe_task_start,
)
from banksia.persistence.models import HumanRequestModel, WorkflowUndoReceiptModel
from banksia.runtime.human_request.records import validate_answered_item_responses
from banksia.runtime.product.command_runs import read_product_command_run
from banksia.runtime.product.human_requests import read_product_human_request
from banksia.runtime.product.tasks import read_product_task
from banksia.workflows.authoring import (
    read_workflow_catalog_entry,
    read_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import WorkflowLibraryAction

type ProposalSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class OperatorProposalResolution:
    """Fresh product truth and human-facing copy for a guarded operation."""

    guard: str
    label: str
    resource_scope: str
    consequence: str


class OperatorProposalResolver:
    """Resolve guarded operations against fresh product truth before proposal."""

    def __init__(self, session_factory: ProposalSessionFactory) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        async with self._session_factory() as session:
            if operation.startswith("workflow_draft_"):
                return await self._resolve_workflow(session, operation, request)
            if operation == "task_start":
                return await self._resolve_task_start(session, request)
            if operation == "task_control":
                return await self._resolve_task_control(session, request)
            if operation == "human_request_respond":
                return await self._resolve_human_response(session, request)
            if operation == "command_run_cancel":
                return await self._resolve_command_cancel(session, request)
        raise ValueError(f"{operation} is not a proposal operation")

    async def _resolve_workflow(
        self,
        session: AsyncSession,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        draft_request = cast(
            WorkflowDraftUndoOperationRequest
            | WorkflowDraftDiscardOperationRequest
            | WorkflowDraftPublishOperationRequest,
            request,
        )
        draft = await read_workflow_draft(
            session,
            draft_id=draft_request.draft_id,
        )
        if draft.etag != draft_request.etag:
            raise ValueError("Workflow proposal does not use the current draft")
        if operation == "workflow_draft_undo":
            undo_request = cast(WorkflowDraftUndoOperationRequest, request)
            receipt_id = await session.scalar(
                select(WorkflowUndoReceiptModel.receipt_id).where(
                    WorkflowUndoReceiptModel.receipt_id == undo_request.receipt_id,
                    WorkflowUndoReceiptModel.draft_id == undo_request.draft_id,
                    WorkflowUndoReceiptModel.expected_etag == undo_request.etag,
                    WorkflowUndoReceiptModel.consumed.is_(False),
                )
            )
            if receipt_id is None:
                raise ValueError("Workflow Undo receipt is not current")
            description = describe_draft_undo(draft)
        elif operation == "workflow_draft_discard":
            description = describe_draft_discard(draft)
        elif operation == "workflow_draft_publish":
            validation = await validate_workflow_draft(
                session,
                draft_id=draft.draft_id,
            )
            if not validation.is_valid or validation.draft.etag != draft.etag:
                raise ValueError("Workflow draft is not publishable")
            description = describe_draft_publish(draft)
        else:
            raise ValueError(f"{operation} is not a Workflow proposal operation")
        return _build_proposal_resolution(draft.etag, description)

    async def _resolve_task_start(
        self,
        session: AsyncSession,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        task_request = cast(TaskStartOperationRequest, request)
        workflow = await read_workflow_catalog_entry(
            session,
            workflow_id=task_request.workflow,
            should_include_revisions=False,
        )
        revision_no = workflow.published_revision_no
        if revision_no is None or WorkflowLibraryAction.START_RUN not in workflow.available_actions:
            raise ValueError("Run start requires a published Workflow")
        return _build_proposal_resolution(
            f"{workflow.workflow_id}:{revision_no}",
            describe_task_start(workflow, task_request),
        )

    async def _resolve_task_control(
        self,
        session: AsyncSession,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        task_request = cast(TaskControlOperationRequest, request)
        task = await read_product_task(session, task_request.task_id)
        action = next(
            (item for item in task.actions if item.id == task_request.action_id),
            None,
        )
        if action is None:
            raise ValueError("Run action is not current")
        return _build_proposal_resolution(
            action.id,
            describe_task_control(task, action),
        )

    async def _resolve_human_response(
        self,
        session: AsyncSession,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        human_request = cast(HumanRequestRespondOperationRequest, request)
        human_view = await read_product_human_request(
            session,
            task_id=human_request.task_id,
            request_id=human_request.request_id,
        )
        action = (
            human_view.action
            if isinstance(human_request.input, OperatorHumanAnswerInput)
            else human_view.cancel_action
        )
        if action is None or action.id != human_request.action_id:
            raise ValueError("Human Request action is not current")
        if isinstance(human_request.input, OperatorHumanAnswerInput):
            source = await session.scalar(
                select(HumanRequestModel).where(
                    HumanRequestModel.task_id == human_request.task_id,
                    HumanRequestModel.request_id == human_request.request_id,
                )
            )
            if source is None:
                raise ValueError("Human Request is not current")
            validate_answered_item_responses(
                source,
                human_request.input.item_responses,
            )
        task = await read_product_task(session, human_request.task_id)
        return _build_proposal_resolution(
            action.id,
            describe_human_response(task, human_view, action),
        )

    async def _resolve_command_cancel(
        self,
        session: AsyncSession,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        command_request = cast(CommandRunCancelOperationRequest, request)
        command = await read_product_command_run(
            session,
            task_id=command_request.task_id,
            command_id=command_request.command_id,
        )
        action = command.cancel_action
        if action is None or action.id != command_request.action_id:
            raise ValueError("Managed Action cancellation is not current")
        task = await read_product_task(session, command_request.task_id)
        return _build_proposal_resolution(
            action.id,
            describe_command_cancel(task, command, action),
        )


def _build_proposal_resolution(
    guard: str,
    description: tuple[str, str, str],
) -> OperatorProposalResolution:
    label, resource_scope, consequence = description
    return OperatorProposalResolution(
        guard=guard,
        label=label,
        resource_scope=resource_scope,
        consequence=consequence,
    )


__all__ = [
    "OperatorProposalResolution",
    "OperatorProposalResolver",
]

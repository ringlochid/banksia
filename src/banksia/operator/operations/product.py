from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, cast

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import Settings
from banksia.operator.operations.catalog import (
    OPERATOR_OPERATION_BY_NAME,
    OperatorOperationName,
)
from banksia.operator.operations.contracts import (
    CommandRunCancelOperationRequest,
    CommandRunGetOperationRequest,
    CommandRunOutputReadOperationRequest,
    HumanRequestRespondOperationRequest,
    OperatorHumanAnswerInput,
    TaskControlOperationRequest,
    TaskGetOperationRequest,
    TaskSearchOperationRequest,
    TaskStartOperationRequest,
    WorkflowDraftCreateOperationRequest,
    WorkflowDraftDiscardOperationRequest,
    WorkflowDraftEditOperationRequest,
    WorkflowDraftPublishOperationRequest,
    WorkflowDraftUndoOperationRequest,
    WorkflowDraftValidateOperationRequest,
    WorkflowGetOperationRequest,
    WorkflowSearchOperationRequest,
)
from banksia.operator.operations.proposal_resolution import (
    OperatorProposalResolution,
    OperatorProposalResolver,
)
from banksia.runtime.contracts.primitives import (
    HumanRequestResolutionSurface,
    TaskEventSource,
)
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.task import (
    CommandRunCancelRequest,
    HumanRequestAnswerInput,
    HumanRequestCancelInput,
    HumanRequestResponseRequest,
    TaskControlRequest,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.command_runs import (
    cancel_product_command_run,
    read_product_command_output,
    read_product_command_run,
)
from banksia.runtime.product.human_requests import respond_to_product_human_request
from banksia.runtime.product.tasks import (
    control_product_task,
    read_product_task,
    search_product_tasks,
    start_product_task,
)
from banksia.workflows.authoring import (
    build_workflow_authoring_options,
    discard_workflow_draft,
    edit_workflow_draft,
    open_workflow_draft,
    publish_workflow_draft,
    read_workflow_catalog_entry,
    search_workflow_catalog,
    undo_workflow_draft,
    validate_workflow_draft,
)
from banksia.workflows.authoring_contracts import map_workflow_published_readback
from banksia.workflows.contracts import PublishedWorkflowRevision

_OPERATOR_ACTOR_REF = "operator"


class OperatorProductOperations(Protocol):
    async def execute(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        *,
        is_confirmed: bool = False,
        confirmed_guard: str | None = None,
    ) -> dict[str, object]: ...

    async def read_guard(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> str | None: ...

    async def is_guard_current(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> bool: ...

    async def resolve_proposal(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> OperatorProposalResolution: ...


class BanksiaOperatorProductOperations:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        settings: Settings,
        dispatch_dependencies: DispatchOpeningDependencies,
        runtime_effect_publisher: RuntimeEffectPublisher | None,
    ) -> None:
        self._session_factory = session_factory
        self._proposal_resolver = OperatorProposalResolver(session_factory)
        self._settings = settings
        self._dispatch_dependencies = dispatch_dependencies
        self._runtime_effect_publisher = runtime_effect_publisher

    async def execute(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        *,
        is_confirmed: bool = False,
        confirmed_guard: str | None = None,
    ) -> dict[str, object]:
        spec = OPERATOR_OPERATION_BY_NAME[operation]
        if spec.effect_policy == "proposal" and not is_confirmed:
            raise ValueError("guarded Operator operation requires confirmation")
        if operation.startswith("workflow_"):
            result = await self._execute_workflow(operation, request)
        elif operation.startswith("task_"):
            result = await self._execute_task(
                operation,
                request,
                is_confirmed=is_confirmed,
                confirmed_guard=confirmed_guard,
            )
        elif operation == "human_request_respond":
            result = await self._execute_human_response(
                cast(HumanRequestRespondOperationRequest, request),
                is_confirmed=is_confirmed,
            )
        else:
            result = await self._execute_command(
                operation,
                request,
                is_confirmed=is_confirmed,
            )
        validated = spec.result_model.model_validate(result)
        return cast(
            dict[str, object],
            validated.model_dump(mode="json", exclude_none=True),
        )

    async def read_guard(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> str | None:
        if OPERATOR_OPERATION_BY_NAME[operation].effect_policy == "proposal":
            return (await self.resolve_proposal(operation, request)).guard
        if operation in {
            "workflow_draft_edit",
        }:
            return cast(str, request.model_dump()["etag"])
        return None

    async def is_guard_current(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> bool:
        try:
            current = await self.resolve_proposal(operation, request)
        except Exception:
            return False
        return current.guard == guard

    async def resolve_proposal(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> OperatorProposalResolution:
        return await self._proposal_resolver.resolve(operation, request)

    async def _execute_workflow(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> object:
        if operation == "workflow_authoring_options":
            return build_workflow_authoring_options(self._settings)
        if operation == "workflow_search":
            search_request = cast(WorkflowSearchOperationRequest, request)
            return await self._read(
                lambda session: search_workflow_catalog(
                    session,
                    query=search_request.query,
                    cursor=search_request.cursor,
                    limit=search_request.limit,
                )
            )
        if operation == "workflow_get":
            get_request = cast(WorkflowGetOperationRequest, request)
            return await self._read(
                lambda session: read_workflow_catalog_entry(
                    session,
                    workflow_id=get_request.workflow_id,
                    revision_no=get_request.revision_no,
                    should_include_revisions=get_request.should_include_revisions,
                    revision_cursor=get_request.revision_cursor,
                    revision_limit=get_request.revision_limit,
                )
            )
        return await self._execute_workflow_draft(operation, request)

    async def _execute_workflow_draft(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> object:
        if operation == "workflow_draft_create":
            create_request = cast(WorkflowDraftCreateOperationRequest, request)
            return await self._write(
                lambda session: open_workflow_draft(
                    session,
                    request=create_request.request,
                )
            )
        if operation == "workflow_draft_edit":
            edit_request = cast(WorkflowDraftEditOperationRequest, request)
            return await self._write(
                lambda session: edit_workflow_draft(
                    session,
                    draft_id=edit_request.draft_id,
                    expected_etag=edit_request.etag,
                    operation=edit_request.operation,
                )
            )
        if operation == "workflow_draft_validate":
            validate_request = cast(WorkflowDraftValidateOperationRequest, request)
            return await self._read(
                lambda session: validate_workflow_draft(
                    session,
                    draft_id=validate_request.draft_id,
                )
            )
        return await self._execute_guarded_workflow_draft(operation, request)

    async def _execute_guarded_workflow_draft(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> object:
        if operation == "workflow_draft_undo":
            undo_request = cast(WorkflowDraftUndoOperationRequest, request)
            return await self._write(
                lambda session: undo_workflow_draft(
                    session,
                    draft_id=undo_request.draft_id,
                    expected_etag=undo_request.etag,
                    receipt_id=undo_request.receipt_id,
                )
            )
        if operation == "workflow_draft_discard":
            discard_request = cast(WorkflowDraftDiscardOperationRequest, request)
            await self._write(
                lambda session: discard_workflow_draft(
                    session,
                    draft_id=discard_request.draft_id,
                    expected_etag=discard_request.etag,
                )
            )
            return {"discarded": True, "draft_id": discard_request.draft_id}
        publish_request = cast(WorkflowDraftPublishOperationRequest, request)
        published = cast(
            PublishedWorkflowRevision,
            await self._write(
                lambda session: publish_workflow_draft(
                    session,
                    draft_id=publish_request.draft_id,
                    expected_etag=publish_request.etag,
                )
            ),
        )
        return map_workflow_published_readback(published)

    async def _execute_task(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        *,
        is_confirmed: bool,
        confirmed_guard: str | None,
    ) -> object:
        if operation == "task_search":
            search_request = cast(TaskSearchOperationRequest, request)
            return await self._read(
                lambda session: search_product_tasks(
                    session,
                    q=search_request.q,
                    status=search_request.status,
                    cursor=search_request.cursor,
                    limit=search_request.limit,
                )
            )
        if operation == "task_get":
            get_request = cast(TaskGetOperationRequest, request)
            return await self._read(lambda session: read_product_task(session, get_request.task_id))
        if not is_confirmed:
            raise ValueError("guarded Operator operation requires confirmation")
        if operation == "task_start":
            return await self._start_task(
                cast(TaskStartOperationRequest, request),
                confirmed_guard=confirmed_guard,
            )
        return await self._control_task(cast(TaskControlOperationRequest, request))

    async def _start_task(
        self,
        request: TaskStartOperationRequest,
        *,
        confirmed_guard: str | None,
    ) -> object:
        expected_workflow_revision = _task_start_guard_revision(
            request,
            confirmed_guard,
        )
        task_request = TaskStartRequest.model_validate(request.model_dump())
        return await self._write(
            lambda session: start_product_task(
                task_request,
                session=session,
                dependencies=self._dispatch_dependencies,
                default_workspace=self._dispatch_dependencies.settings.controller_workspace,
                expected_workflow_revision=expected_workflow_revision,
            )
        )

    async def _control_task(self, request: TaskControlOperationRequest) -> object:
        return await self._write(
            lambda session: control_product_task(
                session,
                task_id=request.task_id,
                action_id=request.action_id,
                request=TaskControlRequest(is_confirmed=True),
                dependencies=self._dispatch_dependencies,
                actor_ref=_OPERATOR_ACTOR_REF,
                event_source=TaskEventSource.CONTROLLER,
                runtime_effect_publisher=self._runtime_effect_publisher,
            )
        )

    async def _execute_human_response(
        self,
        request: HumanRequestRespondOperationRequest,
        *,
        is_confirmed: bool,
    ) -> object:
        if not is_confirmed:
            raise ValueError("guarded Operator operation requires confirmation")
        response_input = (
            HumanRequestAnswerInput.model_validate(request.input.model_dump())
            if isinstance(request.input, OperatorHumanAnswerInput)
            else HumanRequestCancelInput(kind="cancel", is_confirmed=True)
        )
        return await self._write(
            lambda session: respond_to_product_human_request(
                session,
                task_id=request.task_id,
                request_id=request.request_id,
                request=HumanRequestResponseRequest(
                    action_id=request.action_id,
                    input=response_input,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                resolved_by_surface=HumanRequestResolutionSurface.CONTROLLER,
                runtime_effect_publisher=self._runtime_effect_publisher,
            )
        )

    async def _execute_command(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        *,
        is_confirmed: bool,
    ) -> object:
        if operation == "command_run_get":
            get_request = cast(CommandRunGetOperationRequest, request)
            return await self._read(
                lambda session: read_product_command_run(
                    session,
                    task_id=get_request.task_id,
                    command_id=get_request.command_id,
                )
            )
        if operation == "command_run_output_read":
            output_request = cast(CommandRunOutputReadOperationRequest, request)
            return await self._read(
                lambda session: read_product_command_output(
                    session,
                    task_id=output_request.task_id,
                    command_id=output_request.command_id,
                    cursor=output_request.cursor,
                    limit=output_request.limit,
                )
            )
        if not is_confirmed:
            raise ValueError("guarded Operator operation requires confirmation")
        cancel_request = cast(CommandRunCancelOperationRequest, request)
        return await self._write(
            lambda session: cancel_product_command_run(
                session,
                task_id=cancel_request.task_id,
                command_id=cancel_request.command_id,
                request=CommandRunCancelRequest(
                    action_id=cancel_request.action_id,
                    is_confirmed=True,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                runtime_effect_publisher=self._runtime_effect_publisher,
            )
        )

    async def _read(
        self,
        operation: Callable[[AsyncSession], Awaitable[object]],
    ) -> object:
        async with self._session_factory() as session:
            return await operation(session)

    async def _write(
        self,
        operation: Callable[[AsyncSession], Awaitable[object]],
    ) -> object:
        async with self._session_factory() as session:
            try:
                result = await operation(session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            return result


def _task_start_guard_revision(
    request: TaskStartOperationRequest,
    guard: str | None,
) -> int:
    prefix = f"{request.workflow}:"
    if guard is None or not guard.startswith(prefix):
        raise ValueError("confirmed Task start is missing its exact Workflow revision guard")
    revision_text = guard.removeprefix(prefix)
    if not revision_text.isdecimal() or int(revision_text) < 1:
        raise ValueError("confirmed Task start has an invalid Workflow revision guard")
    return int(revision_text)


__all__ = [
    "BanksiaOperatorProductOperations",
    "OperatorProductOperations",
    "OperatorProposalResolution",
]

from __future__ import annotations

from dataclasses import dataclass

from banksia.config import Settings
from banksia.operator.conversation_reads import OperatorSessionFactory
from banksia.operator.tools.contracts import (
    CommandRunCancelInput,
    CommandRunGetInput,
    CommandRunOutputReadInput,
    HumanRequestRespondInput,
    OperatorHumanRequestCancelInput,
    OperatorTool,
    OperatorToolName,
    TaskControlInput,
    TaskGetInput,
    TaskSearchInput,
    bind_operator_tool,
)
from banksia.runtime.contracts.primitives import (
    HumanRequestResolutionSurface,
    TaskEventSource,
)
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunView,
    HumanRequestAnswerInput,
    HumanRequestCancelInput,
    HumanRequestResponseReceipt,
    HumanRequestResponseRequest,
    TaskControlReceipt,
    TaskControlRequest,
    TaskSearchResponse,
    TaskStartReceipt,
    TaskView,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
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

_OPERATOR_ACTOR_REF = "operator"


@dataclass(frozen=True, slots=True)
class _RuntimeOperatorLeaves:
    settings: Settings
    session_factory: OperatorSessionFactory
    dispatch_dependencies: DispatchOpeningDependencies

    async def task_search(self, request: TaskSearchInput) -> TaskSearchResponse:
        async with self.session_factory() as session:
            return await search_product_tasks(
                session,
                q=request.query,
                status=request.status,
                cursor=request.cursor,
                limit=request.limit,
            )

    async def task_get(self, request: TaskGetInput) -> TaskView:
        async with self.session_factory() as session:
            return await read_product_task(session, request.task_id)

    async def task_start(self, request: TaskStartRequest) -> TaskStartReceipt:
        async with self.session_factory() as session:
            return await start_product_task(
                request,
                dependencies=self.dispatch_dependencies,
                session=session,
                default_workspace=self.settings.controller_workspace,
            )

    async def task_control(self, request: TaskControlInput) -> TaskControlReceipt:
        async with self.session_factory() as session:
            return await control_product_task(
                session,
                task_id=request.task_id,
                action_id=request.action_id,
                request=TaskControlRequest(is_confirmed=True),
                dependencies=self.dispatch_dependencies,
                actor_ref=_OPERATOR_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR,
                runtime_effect_publisher=self.dispatch_dependencies.post_commit_publisher,
            )

    async def human_request_respond(
        self,
        request: HumanRequestRespondInput,
    ) -> HumanRequestResponseReceipt:
        product_input: HumanRequestAnswerInput | HumanRequestCancelInput
        if isinstance(request.input, OperatorHumanRequestCancelInput):
            product_input = HumanRequestCancelInput(
                kind="cancel",
                is_confirmed=True,
            )
        else:
            product_input = request.input
        async with self.session_factory() as session:
            return await respond_to_product_human_request(
                session,
                task_id=request.task_id,
                request_id=request.request_id,
                request=HumanRequestResponseRequest(
                    action_id=request.action_id,
                    input=product_input,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                resolved_by_surface=HumanRequestResolutionSurface.OPERATOR,
                runtime_effect_publisher=self.dispatch_dependencies.post_commit_publisher,
            )

    async def command_run_get(self, request: CommandRunGetInput) -> CommandRunView:
        async with self.session_factory() as session:
            return await read_product_command_run(
                session,
                task_id=request.task_id,
                command_id=request.command_id,
            )

    async def command_run_output_read(
        self,
        request: CommandRunOutputReadInput,
    ) -> CommandRunOutputPage:
        async with self.session_factory() as session:
            return await read_product_command_output(
                session,
                task_id=request.task_id,
                command_id=request.command_id,
                cursor=request.cursor,
                limit=request.limit,
            )

    async def command_run_cancel(
        self,
        request: CommandRunCancelInput,
    ) -> CommandRunCancelReceipt:
        async with self.session_factory() as session:
            return await cancel_product_command_run(
                session,
                task_id=request.task_id,
                command_id=request.command_id,
                request=CommandRunCancelRequest(
                    action_id=request.action_id,
                    is_confirmed=True,
                ),
                actor_ref=_OPERATOR_ACTOR_REF,
                event_source=TaskEventSource.OPERATOR,
                runtime_effect_publisher=self.dispatch_dependencies.post_commit_publisher,
            )


def build_runtime_operator_tools(
    *,
    settings: Settings,
    session_factory: OperatorSessionFactory,
    dispatch_dependencies: DispatchOpeningDependencies,
) -> tuple[OperatorTool, ...]:
    leaves = _RuntimeOperatorLeaves(
        settings=settings,
        session_factory=session_factory,
        dispatch_dependencies=dispatch_dependencies,
    )
    return (
        *_build_task_tools(leaves),
        *_build_attention_and_command_tools(leaves),
    )


def _build_task_tools(
    leaves: _RuntimeOperatorLeaves,
) -> tuple[OperatorTool, ...]:
    return (
        bind_operator_tool(
            name=OperatorToolName.TASK_SEARCH,
            description=(
                "Search Runs by task ID, Workflow, prompt, or semantic status. Continue a "
                "page only with the returned cursor."
            ),
            input_model=TaskSearchInput,
            handler=leaves.task_search,
        ),
        bind_operator_tool(
            name=OperatorToolName.TASK_GET,
            description=(
                "Read one current Run with its team, Work Plan, attention, recent activity, "
                "result, loose file references, and currently legal actions."
            ),
            input_model=TaskGetInput,
            handler=leaves.task_get,
        ),
        bind_operator_tool(
            name=OperatorToolName.TASK_START,
            description=(
                "Start one Run from a published Workflow using the exact prompt, optional "
                "workspace, and loose file references supplied by the user."
            ),
            input_model=TaskStartRequest,
            handler=leaves.task_start,
        ),
        bind_operator_tool(
            name=OperatorToolName.TASK_CONTROL,
            description=(
                "Apply one current pause, resume, or cancel action using the opaque action "
                "ID returned by task_get."
            ),
            input_model=TaskControlInput,
            handler=leaves.task_control,
        ),
    )


def _build_attention_and_command_tools(
    leaves: _RuntimeOperatorLeaves,
) -> tuple[OperatorTool, ...]:
    return (
        bind_operator_tool(
            name=OperatorToolName.HUMAN_REQUEST_RESPOND,
            description=(
                "Answer or cancel one open Human Request using its current opaque action ID "
                "and the response shape returned by task_get."
            ),
            input_model=HumanRequestRespondInput,
            handler=leaves.human_request_respond,
        ),
        bind_operator_tool(
            name=OperatorToolName.COMMAND_RUN_GET,
            description=(
                "Read one managed Command Run state, outcome, output link, and current "
                "cancellation action."
            ),
            input_model=CommandRunGetInput,
            handler=leaves.command_run_get,
        ),
        bind_operator_tool(
            name=OperatorToolName.COMMAND_RUN_OUTPUT_READ,
            description=(
                "Read one sanitized bounded Command Run output page. Continue only with the "
                "returned cursor."
            ),
            input_model=CommandRunOutputReadInput,
            handler=leaves.command_run_output_read,
        ),
        bind_operator_tool(
            name=OperatorToolName.COMMAND_RUN_CANCEL,
            description=(
                "Request cancellation of one current managed Command Run using the opaque "
                "action ID returned by command_run_get."
            ),
            input_model=CommandRunCancelInput,
            handler=leaves.command_run_cancel,
        ),
    )


__all__ = ["build_runtime_operator_tools"]

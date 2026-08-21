from typing import Any

from fastapi import APIRouter

from oh_my_subagents.interfaces.http.contracts.operation_failure import OperationFailure
from oh_my_subagents.interfaces.http.routers.command_runs import router as command_runs_router
from oh_my_subagents.interfaces.http.routers.human_requests import router as human_requests_router
from oh_my_subagents.interfaces.http.routers.operator import router as operator_router
from oh_my_subagents.interfaces.http.routers.task_activities import router as task_activities_router
from oh_my_subagents.interfaces.http.routers.tasks import router as tasks_router
from oh_my_subagents.interfaces.http.routers.workflows import router as workflows_router
from oh_my_subagents.runtime.product.paths import PRODUCT_API_PREFIX

_SHARED_OPERATION_FAILURE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": OperationFailure} for status_code in (400, 403, 404, 409, 422, 500)
}

api_router = APIRouter(prefix=PRODUCT_API_PREFIX)
api_router.include_router(
    workflows_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    tasks_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    task_activities_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    human_requests_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    command_runs_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    operator_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)

__all__ = ["api_router"]

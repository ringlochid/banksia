from typing import Any

from fastapi import APIRouter

from autoclaw.interfaces.http.contracts.operation_failure import OperationFailure
from autoclaw.interfaces.http.routers.authoring import router as authoring_router
from autoclaw.interfaces.http.routers.control import router as control_router
from autoclaw.interfaces.http.routers.definitions import router as definitions_router
from autoclaw.interfaces.http.routers.health import router as health_router
from autoclaw.interfaces.http.routers.runtime import router as runtime_router
from autoclaw.interfaces.http.routers.tasks import router as tasks_router

_SHARED_OPERATION_FAILURE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": OperationFailure} for status_code in (400, 403, 404, 409, 422, 500)
}

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(
    definitions_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    authoring_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    tasks_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    runtime_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)
api_router.include_router(
    control_router,
    responses=_SHARED_OPERATION_FAILURE_RESPONSES,
)

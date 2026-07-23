from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.dependencies import (
    read_dispatch_opening_dependencies,
)
from banksia.interfaces.http.errors import raise_runtime_exception
from banksia.persistence.session import get_db_session
from banksia.runtime.contracts import TaskStartRequest, TaskStartResponse
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.task_start import start_task as start_task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type DispatchOpeningDependenciesDep = Annotated[
    DispatchOpeningDependencies,
    Depends(read_dispatch_opening_dependencies),
]


@router.post("/start", response_model=TaskStartResponse)
async def start_task(
    request: TaskStartRequest,
    session: DBSession,
    dependencies: DispatchOpeningDependenciesDep,
) -> TaskStartResponse:
    try:
        return await start_task_service(
            request,
            session=session,
            dependencies=dependencies,
            default_workspace=dependencies.settings.controller_workspace,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


__all__ = ["router"]

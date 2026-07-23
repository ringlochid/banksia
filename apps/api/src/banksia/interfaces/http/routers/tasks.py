from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.dependencies import (
    read_runtime_effect_publisher,
    read_support_projection_publisher,
)
from banksia.interfaces.http.errors import raise_runtime_exception
from banksia.persistence.session import get_db_session
from banksia.runtime.contracts import TaskStartRequest, TaskStartResponse
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.task_start import start_task as start_task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]
type SupportProjectionPublisherDep = Annotated[
    SupportProjectionPublisher | None,
    Depends(read_support_projection_publisher),
]


@router.post("/start", response_model=TaskStartResponse)
async def start_task(
    request: TaskStartRequest,
    session: DBSession,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
    support_projection_publisher: SupportProjectionPublisherDep,
) -> TaskStartResponse:
    try:
        return await start_task_service(
            request,
            session=session,
            runtime_effect_publisher=runtime_effect_publisher,
            support_projection_publisher=support_projection_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


__all__ = ["router"]

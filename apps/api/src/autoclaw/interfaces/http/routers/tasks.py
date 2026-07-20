from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.registry.task_start import start_task_from_definition
from autoclaw.interfaces.http.dependencies import (
    read_runtime_effect_publisher,
    read_support_projection_publisher,
)
from autoclaw.interfaces.http.errors import raise_runtime_exception
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import TaskStartRequest, TaskStartResponse
from autoclaw.runtime.node_operations.follow_on import SupportProjectionPublisher
from autoclaw.runtime.post_commit import RuntimeEffectPublisher

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
        return await start_task_from_definition(
            request,
            session=session,
            runtime_effect_publisher=runtime_effect_publisher,
            support_projection_publisher=support_projection_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)

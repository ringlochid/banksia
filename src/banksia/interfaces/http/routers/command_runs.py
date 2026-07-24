from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.dependencies import (
    read_control_actor_ref,
    read_runtime_effect_publisher,
)
from banksia.interfaces.http.errors import raise_runtime_exception
from banksia.persistence.session import get_db_session
from banksia.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunView,
)
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.command_runs import (
    cancel_product_command_run,
    read_product_command_output,
    read_product_command_run,
)

router = APIRouter(tags=["command-runs"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ActorRef = Annotated[str | None, Depends(read_control_actor_ref)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]
type OutputCursor = Annotated[str | None, Query(min_length=1)]
type OutputLimit = Annotated[int, Query(ge=1, le=65_536)]


@router.get(
    "/tasks/{task_id}/command-runs/{command_id}",
    response_model=CommandRunView,
)
async def get_command_run(
    task_id: str,
    command_id: str,
    session: DBSession,
) -> CommandRunView:
    try:
        return await read_product_command_run(
            session,
            task_id=task_id,
            command_id=command_id,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.get(
    "/tasks/{task_id}/command-runs/{command_id}/output",
    response_model=CommandRunOutputPage,
)
async def get_command_run_output(
    task_id: str,
    command_id: str,
    session: DBSession,
    cursor: OutputCursor = None,
    limit: OutputLimit = 65_536,
) -> CommandRunOutputPage:
    try:
        return await read_product_command_output(
            session,
            task_id=task_id,
            command_id=command_id,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/command-runs/{command_id}/cancel",
    response_model=CommandRunCancelReceipt,
)
async def post_command_run_cancel(
    task_id: str,
    command_id: str,
    request_body: CommandRunCancelRequest,
    session: DBSession,
    actor_ref: ActorRef,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> CommandRunCancelReceipt:
    try:
        return await cancel_product_command_run(
            session,
            task_id=task_id,
            command_id=command_id,
            request=request_body,
            actor_ref=actor_ref,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


__all__ = ["router"]

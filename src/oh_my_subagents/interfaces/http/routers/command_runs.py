from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.interfaces.http.dependencies import (
    read_control_actor_ref,
    read_runtime_effect_publisher,
)
from oh_my_subagents.interfaces.http.errors import raise_runtime_exception
from oh_my_subagents.persistence.session import get_db_session
from oh_my_subagents.runtime.contracts.task import (
    CommandRunCancelReceipt,
    CommandRunCancelRequest,
    CommandRunOutputPage,
    CommandRunPage,
    CommandRunView,
)
from oh_my_subagents.runtime.post_commit import RuntimeEffectPublisher
from oh_my_subagents.runtime.product.command_runs import (
    cancel_product_command_run,
    list_product_command_run_page,
    read_product_command_output,
    read_product_command_run,
)
from oh_my_subagents.runtime.task_control.service import runtime_task_read

router = APIRouter(tags=["command-runs"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ActorRef = Annotated[str | None, Depends(read_control_actor_ref)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]
type OutputCursor = Annotated[str | None, Query(min_length=1)]
type OutputLimit = Annotated[int, Query(ge=1, le=65_536)]
type HistoryCursor = Annotated[str | None, Query(min_length=1)]
type HistoryLimit = Annotated[int, Query(ge=1, le=200)]


@router.get(
    "/tasks/{task_id}/command-runs",
    response_model=CommandRunPage,
)
async def get_command_runs(
    task_id: str,
    session: DBSession,
    cursor: HistoryCursor = None,
    limit: HistoryLimit = 50,
) -> CommandRunPage:
    try:
        await runtime_task_read(session, task_id)
        return await list_product_command_run_page(
            session,
            task_id=task_id,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


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

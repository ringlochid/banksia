from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.interfaces.http.dependencies import (
    read_control_actor_ref,
    read_runtime_effect_publisher,
)
from oh_my_subagents.interfaces.http.errors import raise_runtime_exception
from oh_my_subagents.persistence.session import get_db_session
from oh_my_subagents.runtime.contracts.primitives import HumanRequestResolutionSurface
from oh_my_subagents.runtime.contracts.task import (
    HumanRequestResponseReceipt,
    HumanRequestResponseRequest,
    HumanRequestView,
)
from oh_my_subagents.runtime.post_commit import RuntimeEffectPublisher
from oh_my_subagents.runtime.product.human_requests import (
    read_product_human_request,
    respond_to_product_human_request,
)

router = APIRouter(tags=["human-requests"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ActorRef = Annotated[str | None, Depends(read_control_actor_ref)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]


@router.get(
    "/tasks/{task_id}/human-requests/{request_id}",
    response_model=HumanRequestView,
)
async def get_human_request(
    task_id: str,
    request_id: str,
    session: DBSession,
) -> HumanRequestView:
    try:
        return await read_product_human_request(
            session,
            task_id=task_id,
            request_id=request_id,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/human-requests/{request_id}/responses",
    response_model=HumanRequestResponseReceipt,
)
async def post_human_request_response(
    task_id: str,
    request_id: str,
    request_body: HumanRequestResponseRequest,
    session: DBSession,
    actor_ref: ActorRef,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> HumanRequestResponseReceipt:
    try:
        return await respond_to_product_human_request(
            session,
            task_id=task_id,
            request_id=request_id,
            request=request_body,
            actor_ref=actor_ref,
            resolved_by_surface=HumanRequestResolutionSurface.CONTROL_UI,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


__all__ = ["router"]

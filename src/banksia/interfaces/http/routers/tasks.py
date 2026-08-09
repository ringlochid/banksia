from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.interfaces.http.dependencies import (
    read_control_actor_ref,
    read_dispatch_opening_dependencies,
    read_provider_adapter_registry,
    read_runtime_effect_publisher,
)
from banksia.interfaces.http.errors import raise_runtime_exception
from banksia.persistence.session import get_db_session
from banksia.runtime.contracts.primitives import TaskEventSource
from banksia.runtime.contracts.start import TaskStartRequest
from banksia.runtime.contracts.task import (
    MemberSteerReceipt,
    MemberSteerRequest,
    TaskControlReceipt,
    TaskControlRequest,
    TaskSearchResponse,
    TaskStartReceipt,
    TaskView,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.member_steering import steer_product_task_member
from banksia.runtime.product.tasks import (
    control_product_task,
    read_product_task,
    search_product_tasks,
    start_product_task,
)
from banksia.runtime.providers import ProviderAdapterRegistry

router = APIRouter(tags=["tasks"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type ActorRef = Annotated[str | None, Depends(read_control_actor_ref)]
type RuntimeEffectPublisherDep = Annotated[
    RuntimeEffectPublisher | None,
    Depends(read_runtime_effect_publisher),
]
type DispatchDependencies = Annotated[
    DispatchOpeningDependencies,
    Depends(read_dispatch_opening_dependencies),
]
type TaskCursor = Annotated[str | None, Query(min_length=1)]
type TaskLimit = Annotated[int, Query(ge=1, le=100)]
type ProviderAdapters = Annotated[
    ProviderAdapterRegistry,
    Depends(read_provider_adapter_registry),
]


@router.get("/tasks", response_model=TaskSearchResponse)
async def get_tasks(
    session: DBSession,
    q: str | None = None,
    status_filter: Annotated[str, Query(alias="status")] = "any",
    cursor: TaskCursor = None,
    limit: TaskLimit = 50,
) -> TaskSearchResponse:
    try:
        return await search_product_tasks(
            session,
            q=q,
            status=status_filter,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.post(
    "/tasks",
    response_model=TaskStartReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_task(
    request_body: TaskStartRequest,
    request: Request,
    session: DBSession,
    dependencies: DispatchDependencies,
) -> TaskStartReceipt:
    del request
    try:
        return await start_product_task(
            request_body,
            session=session,
            dependencies=dependencies,
            default_workspace=dependencies.settings.controller_workspace,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.get("/tasks/{task_id}", response_model=TaskView)
async def get_task(
    task_id: str,
    session: DBSession,
    provider_adapters: ProviderAdapters,
) -> TaskView:
    try:
        return await read_product_task(
            session,
            task_id,
            provider_adapters=provider_adapters,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/members/{member_id}/steers",
    response_model=MemberSteerReceipt,
)
async def post_member_steer(
    task_id: str,
    member_id: str,
    request_body: MemberSteerRequest,
    session: DBSession,
    actor_ref: ActorRef,
    provider_adapters: ProviderAdapters,
) -> MemberSteerReceipt:
    try:
        return await steer_product_task_member(
            session,
            task_id=task_id,
            member_id=member_id,
            request=request_body,
            adapters=provider_adapters,
            actor_ref=actor_ref,
            event_source=TaskEventSource.CONTROL_API,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


@router.post(
    "/tasks/{task_id}/controls/{action_id}",
    response_model=TaskControlReceipt,
)
async def post_task_control(
    task_id: str,
    action_id: str,
    request_body: TaskControlRequest,
    session: DBSession,
    actor_ref: ActorRef,
    dependencies: DispatchDependencies,
    runtime_effect_publisher: RuntimeEffectPublisherDep,
) -> TaskControlReceipt:
    try:
        return await control_product_task(
            session,
            task_id=task_id,
            action_id=action_id,
            request=request_body,
            dependencies=dependencies,
            actor_ref=actor_ref,
            event_source=TaskEventSource.CONTROL_API,
            runtime_effect_publisher=runtime_effect_publisher,
        )
    except Exception as exc:  # pragma: no cover - thin transport mapping
        raise_runtime_exception(exc)


__all__ = ["router"]

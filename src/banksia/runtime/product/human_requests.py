from __future__ import annotations

from collections import defaultdict
from secrets import token_urlsafe
from typing import Literal, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import HumanRequestFileReferenceModel, HumanRequestModel
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts import (
    FileReference,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestResolveRequest,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.contracts.task import (
    HumanRequestProductStatus,
    HumanRequestResolutionView,
    HumanRequestResponseReceipt,
    HumanRequestResponseRequest,
    HumanRequestView,
    ProductAction,
    ProductActionConfirmation,
    TaskMemberReference,
)
from banksia.runtime.errors import RuntimeOperationError, missing_resource_error
from banksia.runtime.human_request.records import (
    human_request_read_from_model,
    read_human_request_file_references,
)
from banksia.runtime.human_request.service import (
    persist_human_request_resolution,
    resolve_human_request,
)
from banksia.runtime.post_commit import RuntimeEffectPublisher
from banksia.runtime.product.action_ids import product_action_id, select_action_kind
from banksia.runtime.product.paths import build_product_api_path
from banksia.runtime.product.presenters import (
    read_source_member_reference,
    read_source_member_references,
)


class ProductHumanRequestCollection(NamedTuple):
    items: tuple[HumanRequestView, ...]
    total_count: int
    is_truncated: bool


async def list_product_human_requests(
    session: AsyncSession,
    *,
    task_id: str,
    terminal_limit: int = 20,
) -> ProductHumanRequestCollection:
    if not 0 <= terminal_limit <= 100:
        raise ValueError("terminal Human Request limit must be between 0 and 100")
    open_rows = tuple(
        await session.scalars(
            select(HumanRequestModel.request_id)
            .where(
                HumanRequestModel.task_id == task_id,
                HumanRequestModel.status == "open",
            )
            .order_by(HumanRequestModel.opened_at.desc(), HumanRequestModel.request_id.desc())
        )
    )
    terminal_rows = tuple(
        await session.scalars(
            select(HumanRequestModel.request_id)
            .where(
                HumanRequestModel.task_id == task_id,
                HumanRequestModel.status != "open",
            )
            .order_by(HumanRequestModel.resolved_at.desc(), HumanRequestModel.request_id.desc())
            .limit(terminal_limit + 1)
        )
    )
    total_count = int(
        await session.scalar(
            select(func.count())
            .select_from(HumanRequestModel)
            .where(HumanRequestModel.task_id == task_id)
        )
        or 0
    )
    selected_ids = (*open_rows, *terminal_rows[:terminal_limit])
    sources = tuple(
        await session.scalars(
            select(HumanRequestModel).where(HumanRequestModel.request_id.in_(selected_ids))
        )
    )
    sources_by_id = {source.request_id: source for source in sources}
    files_by_request = await _read_human_request_files(session, request_ids=selected_ids)
    members = await read_source_member_references(
        session,
        task_id=task_id,
        source_dispatch_ids=(source.source_dispatch_id for source in sources),
    )
    return ProductHumanRequestCollection(
        items=tuple(
            _present_human_request(
                source,
                files=files_by_request.get(request_id, ()),
                member=members.get(source.source_dispatch_id),
            )
            for request_id in selected_ids
            if (source := sources_by_id.get(request_id)) is not None
        ),
        total_count=total_count,
        is_truncated=len(terminal_rows) > terminal_limit,
    )


async def respond_to_product_human_request(
    session: AsyncSession,
    *,
    task_id: str,
    request_id: str,
    request: HumanRequestResponseRequest,
    actor_ref: str | None,
    resolved_by_surface: HumanRequestResolutionSurface,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
) -> HumanRequestResponseReceipt:
    source = await session.scalar(
        select(HumanRequestModel).where(
            HumanRequestModel.task_id == task_id,
            HumanRequestModel.request_id == request_id,
        )
    )
    if source is None:
        raise missing_resource_error("That input request could not be found.")
    candidates = (
        (_human_action_id(source, "answer"), "answer"),
        (_human_action_id(source, "cancel"), "cancel"),
    )
    action_kind = select_action_kind(request.action_id, candidates)
    if source.status != "open" or action_kind is None or action_kind != request.input.kind:
        raise _action_unavailable()

    if request.input.kind == "answer":
        await resolve_human_request(
            session,
            task_id=task_id,
            request_id=request_id,
            request=HumanRequestResolveRequest(
                item_responses=request.input.item_responses,
            ),
            actor_ref=actor_ref,
            resolved_by_surface=resolved_by_surface,
            runtime_effect_publisher=runtime_effect_publisher,
        )
        status_message = (
            "Your answer was saved. The run will update separately when work continues."
        )
    else:
        resolution = HumanRequestResolution(
            request_id=source.request_id,
            task_id=source.task_id,
            resolution_kind=HumanRequestResolutionKind.CANCELLED,
            summary="The input request was cancelled by the user.",
            resolved_by_actor_ref=actor_ref,
            resolved_by_surface=resolved_by_surface,
            resolved_at=utc_now(),
        )
        won = await persist_human_request_resolution(
            session,
            source=source,
            resolution=resolution,
            runtime_effect_publisher=runtime_effect_publisher,
        )
        if not won:
            raise _action_unavailable()
        status_message = "The input request was cancelled. The run will update separately."
    current = await read_product_human_request(
        session,
        task_id=task_id,
        request_id=request_id,
    )
    return HumanRequestResponseReceipt(
        receipt_id=f"receipt.{token_urlsafe(24)}",
        status_message=status_message,
        request=current,
    )


async def read_product_human_request(
    session: AsyncSession,
    *,
    task_id: str,
    request_id: str,
) -> HumanRequestView:
    source = await session.scalar(
        select(HumanRequestModel).where(
            HumanRequestModel.task_id == task_id,
            HumanRequestModel.request_id == request_id,
        )
    )
    if source is None:
        raise missing_resource_error("That input request could not be found.")
    files = await read_human_request_file_references(session, request_id=request_id)
    member = await read_source_member_reference(
        session,
        task_id=task_id,
        source_dispatch_id=source.source_dispatch_id,
    )
    return _present_human_request(source, files=files, member=member)


def _present_human_request(
    source: HumanRequestModel,
    *,
    files: tuple[FileReference, ...],
    member: TaskMemberReference | None,
) -> HumanRequestView:
    readback = human_request_read_from_model(source, files=files)
    request = readback.request
    response_action = None
    cancel_action = None
    if source.status == "open":
        response_action = _human_action(source, kind="answer")
        cancel_action = _human_action(source, kind="cancel")
    resolution = None
    if readback.resolution is not None:
        resolution_kind = readback.resolution.resolution_kind.value
        resolution = HumanRequestResolutionView(
            status=_product_resolution_status(resolution_kind),
            summary=readback.resolution.summary,
            resolved_at=readback.resolution.resolved_at,
        )
    return HumanRequestView(
        id=request.request_id,
        kind=request.kind.value,
        summary=request.summary,
        items=request.items,
        files=request.files,
        opened_at=request.opened_at,
        due_at=request.timeout.due_at,
        status=_product_request_status(request.status.value),
        member=member,
        action=response_action,
        cancel_action=cancel_action,
        resolution=resolution,
    )


async def _read_human_request_files(
    session: AsyncSession,
    *,
    request_ids: tuple[str, ...],
) -> dict[str, tuple[FileReference, ...]]:
    if not request_ids:
        return {}
    rows = await session.scalars(
        select(HumanRequestFileReferenceModel)
        .where(HumanRequestFileReferenceModel.request_id.in_(request_ids))
        .order_by(
            HumanRequestFileReferenceModel.request_id,
            HumanRequestFileReferenceModel.order_index,
        )
    )
    grouped: defaultdict[str, list[FileReference]] = defaultdict(list)
    for row in rows:
        grouped[row.request_id].append(FileReference(path=row.path, description=row.description))
    return {request_id: tuple(files) for request_id, files in grouped.items()}


def _human_action(source: HumanRequestModel, *, kind: str) -> ProductAction:
    is_cancel = kind == "cancel"
    if is_cancel:
        input_schema = {
            "type": "object",
            "properties": {
                "kind": {"const": "cancel"},
                "confirmed": {"const": True},
            },
            "required": ["kind", "confirmed"],
            "additionalProperties": False,
        }
    else:
        input_schema = {
            "type": "object",
            "properties": {
                "kind": {"const": "answer"},
                "item_responses": {"type": "object"},
            },
            "required": ["kind", "item_responses"],
            "additionalProperties": False,
        }
    return ProductAction(
        id=_human_action_id(source, kind),
        kind=kind,
        label="Cancel request" if is_cancel else "Submit answer",
        href=build_product_api_path(
            f"/tasks/{source.task_id}/human-requests/{source.request_id}/responses"
        ),
        confirmation=ProductActionConfirmation(
            is_required=is_cancel,
            title="Cancel this request?" if is_cancel else "Submit this answer?",
            consequence=(
                "The team will continue without an answer to this request."
                if is_cancel
                else "The answer is saved now; continuation happens separately."
            ),
        ),
        input_schema=input_schema,
    )


def _product_resolution_status(
    resolution_kind: str,
) -> Literal["answered", "expired", "cancelled"]:
    if resolution_kind == "answered":
        return "answered"
    if resolution_kind == "timed_out":
        return "expired"
    if resolution_kind == "cancelled":
        return "cancelled"
    raise RuntimeError("Human Request has an unsupported resolution")


def _product_request_status(status: str) -> HumanRequestProductStatus:
    if status == "open":
        return "open"
    if status == "resolved":
        return "answered"
    if status == "timed_out":
        return "expired"
    if status == "cancelled":
        return "cancelled"
    raise RuntimeError("Human Request has an unsupported controller state")


def _human_action_id(source: HumanRequestModel, kind: str) -> str:
    return product_action_id(
        "human-request",
        source.task_id,
        source.request_id,
        source.status,
        source.opened_at,
        kind,
    )


def _action_unavailable() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.CONFLICT,
        summary="That input action is no longer available.",
        is_retryable=False,
        suggested_next_step="Reload the request and use one of its current actions.",
        status_code_override=409,
    )


__all__ = [
    "ProductHumanRequestCollection",
    "list_product_human_requests",
    "read_product_human_request",
    "respond_to_product_human_request",
]

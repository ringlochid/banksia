from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    SchemaError,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    HumanRequestFileReferenceModel,
    HumanRequestModel,
)
from banksia.runtime.contracts import (
    FileReference,
    HumanRequestItem,
    HumanRequestItemAnswer,
    HumanRequestKind,
    HumanRequestOptionAnswer,
    HumanRequestOtherAnswer,
    HumanRequestRead,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestResolveRequest,
    HumanRequestSkippedAnswer,
    HumanRequestStatus,
    HumanRequestTimeout,
    HumanRequestValueAnswer,
    PendingHumanRequest,
)
from banksia.runtime.errors import illegal_state_error, invalid_request_shape_error


def human_request_read_from_model(
    row: HumanRequestModel,
    *,
    files: tuple[FileReference, ...] = (),
) -> HumanRequestRead:
    return HumanRequestRead(
        request=pending_human_request_from_model(row, files=files),
        resolution=human_request_resolution_from_model(row),
    )


def validate_answered_item_responses(
    source: HumanRequestModel,
    item_responses: Mapping[str, HumanRequestItemAnswer],
) -> None:
    request_items = tuple(
        HumanRequestItem.model_validate(item) for item in source.request_items_json
    )
    request_item_ids = {item.id for item in request_items}
    if set(item_responses) != request_item_ids:
        raise invalid_request_shape_error(
            "human request resolution must answer every request item exactly once"
        )

    request_items_by_id = {item.id: item for item in request_items}
    for item_id, response in item_responses.items():
        _validate_answered_item_response(request_items_by_id[item_id], response)


def pending_human_request_from_model(
    row: HumanRequestModel,
    *,
    files: tuple[FileReference, ...] = (),
) -> PendingHumanRequest:
    default_behavior = None
    if row.default_behavior_json is not None:
        value = row.default_behavior_json.get("value")
        default_behavior = value if isinstance(value, str) else None
    return PendingHumanRequest(
        request_id=row.request_id,
        task_id=row.task_id,
        flow_id=row.flow_id,
        assignment_id=row.assignment_id,
        attempt_id=row.attempt_id,
        summary=row.request_summary,
        kind=HumanRequestKind(row.request_kind),
        source_dispatch_id=row.source_dispatch_id,
        items=tuple(HumanRequestItem.model_validate(item) for item in row.request_items_json),
        files=files,
        timeout=HumanRequestTimeout(
            due_at=(_coerce_datetime_to_utc(row.due_at) if row.due_at is not None else None),
            default_behavior=default_behavior,
        ),
        opened_at=_coerce_datetime_to_utc(row.opened_at),
        status=HumanRequestStatus(row.status),
        successor_dispatch_id=row.successor_dispatch_id,
    )


async def read_human_request_file_references(
    session: AsyncSession,
    *,
    request_id: str,
) -> tuple[FileReference, ...]:
    rows = tuple(
        await session.scalars(
            select(HumanRequestFileReferenceModel)
            .where(HumanRequestFileReferenceModel.request_id == request_id)
            .order_by(HumanRequestFileReferenceModel.order_index)
        )
    )
    return tuple(FileReference(path=row.path, description=row.description) for row in rows)


def human_request_resolution_from_model(
    row: HumanRequestModel,
) -> HumanRequestResolution | None:
    if row.status == HumanRequestStatus.OPEN.value:
        return None
    if (
        row.resolution_kind is None
        or row.resolution_summary is None
        or row.resolved_by_surface is None
        or row.resolved_at is None
    ):
        raise illegal_state_error(
            f"terminal human request '{row.request_id}' is missing resolution"
        )
    return HumanRequestResolution(
        request_id=row.request_id,
        task_id=row.task_id,
        resolution_kind=HumanRequestResolutionKind(row.resolution_kind),
        item_responses=_validated_item_responses(row.item_responses_json),
        summary=row.resolution_summary,
        resolved_at=_coerce_datetime_to_utc(row.resolved_at),
        resolved_by_actor_ref=row.resolved_by_actor_ref,
        resolved_by_surface=HumanRequestResolutionSurface(row.resolved_by_surface),
    )


def _validated_item_responses(
    value: dict[str, object] | None,
) -> dict[str, HumanRequestItemAnswer] | None:
    if value is None:
        return None
    return HumanRequestResolveRequest.model_validate(
        {"item_responses": value},
        strict=True,
    ).item_responses


def _validate_answered_item_response(
    request_item: HumanRequestItem,
    item_response: HumanRequestItemAnswer,
) -> None:
    if isinstance(item_response, HumanRequestSkippedAnswer):
        if not request_item.allow_skip:
            raise invalid_request_shape_error(
                f"human request item '{request_item.id}' does not allow Skip"
            )
        return

    if request_item.options is not None:
        if isinstance(item_response, HumanRequestOtherAnswer):
            if not request_item.allow_other:
                raise invalid_request_shape_error(
                    f"human request item '{request_item.id}' does not allow Other"
                )
            return
        if not isinstance(item_response, HumanRequestOptionAnswer):
            raise invalid_request_shape_error(
                f"human request item '{request_item.id}' requires one tagged option answer"
            )
        option_ids = {option.id for option in request_item.options}
        if item_response.option_id not in option_ids:
            raise invalid_request_shape_error(
                f"unknown option for human request item '{request_item.id}'"
            )
        return

    if not isinstance(item_response, HumanRequestValueAnswer):
        raise invalid_request_shape_error(
            f"human request item '{request_item.id}' requires one tagged value answer"
        )
    response_schema = request_item.response_schema
    if response_schema is None:
        raise illegal_state_error(
            f"human request item '{request_item.id}' is missing its response contract"
        )
    try:
        Draft202012Validator.check_schema(response_schema)
        Draft202012Validator(response_schema).validate(item_response.value)
    except SchemaError as exc:
        raise illegal_state_error(
            f"response_schema is invalid for human request item '{request_item.id}'"
        ) from exc
    except JsonSchemaValidationError as exc:
        raise invalid_request_shape_error(
            f"response does not match response_schema for human request item '{request_item.id}'"
        ) from exc


def _coerce_datetime_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "human_request_read_from_model",
    "human_request_resolution_from_model",
    "pending_human_request_from_model",
    "read_human_request_file_references",
    "validate_answered_item_responses",
]

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    SchemaError,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import JsonValue, TypeAdapter

from autoclaw.persistence.models import HumanRequestModel
from autoclaw.runtime.contracts import (
    HumanRequestContextRef,
    HumanRequestItem,
    HumanRequestKind,
    HumanRequestRead,
    HumanRequestResolution,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
    HumanRequestTimeout,
    PendingHumanRequest,
)
from autoclaw.runtime.errors import illegal_state_error, invalid_request_shape_error

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def human_request_read_from_model(row: HumanRequestModel) -> HumanRequestRead:
    return HumanRequestRead(
        request=pending_human_request_from_model(row),
        resolution=human_request_resolution_from_model(row),
    )


def validate_answered_item_responses(
    source: HumanRequestModel,
    item_responses: Mapping[str, object],
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


def pending_human_request_from_model(row: HumanRequestModel) -> PendingHumanRequest:
    default_behavior = None
    if row.default_behavior_json is not None:
        value = row.default_behavior_json.get("value")
        default_behavior = value if isinstance(value, str) else None
    context_refs = row.context_refs_json or []
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
        context_refs=tuple(
            HumanRequestContextRef.model_validate(context_ref) for context_ref in context_refs
        ),
        timeout=HumanRequestTimeout(
            due_at=(_coerce_datetime_to_utc(row.due_at) if row.due_at is not None else None),
            default_behavior=default_behavior,
        ),
        suggested_human_instruction=row.suggested_human_instruction,
        opened_at=_coerce_datetime_to_utc(row.opened_at),
        status=HumanRequestStatus(row.status),
        successor_dispatch_id=row.successor_dispatch_id,
    )


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
        item_responses=_validated_json_object(row.item_responses_json),
        policy_basis=_validated_json_object(row.resolution_policy_basis_json),
        summary=row.resolution_summary,
        resolved_at=_coerce_datetime_to_utc(row.resolved_at),
        resolved_by_actor_ref=row.resolved_by_actor_ref,
        resolved_by_surface=HumanRequestResolutionSurface(row.resolved_by_surface),
    )


def _validated_json_object(
    value: dict[str, object] | None,
) -> dict[str, JsonValue] | None:
    if value is None:
        return None
    return _JSON_OBJECT_ADAPTER.validate_python(value, strict=True)


def _validate_answered_item_response(
    request_item: HumanRequestItem,
    item_response: object,
) -> None:
    if request_item.options is not None:
        if not isinstance(item_response, str):
            raise invalid_request_shape_error(
                f"human request item '{request_item.id}' requires one option id"
            )
        option_ids = {option.id for option in request_item.options}
        if item_response not in option_ids:
            raise invalid_request_shape_error(
                f"unknown option for human request item '{request_item.id}'"
            )
        return

    response_schema = request_item.response_schema
    if response_schema is None:
        raise illegal_state_error(
            f"human request item '{request_item.id}' is missing its response contract"
        )
    try:
        Draft202012Validator.check_schema(response_schema)
        Draft202012Validator(response_schema).validate(item_response)
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
    "validate_answered_item_responses",
]

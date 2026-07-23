from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    SchemaError,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.primitives import (
    HumanRequestKind,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
    TaskIdentifier,
)
from banksia.runtime.contracts.refs import FileReference, validate_file_reference_limit
from banksia.runtime.contracts.text import normalize_exact_text, normalize_optional_text

_SUMMARY_MAX_CHARACTERS = 2_048
_ITEM_PROMPT_MAX_CHARACTERS = 4_096
_OPTION_TITLE_MAX_CHARACTERS = 255
_OPTION_DESCRIPTION_MAX_CHARACTERS = 1_024
_STRUCTURED_VALUE_MAX_BYTES = 64 * 1024
_STRUCTURED_VALUE_MAX_DEPTH = 16
_STRUCTURED_VALUE_MAX_COLLECTION_NODES = 1_024
_ALLOWED_SCHEMA_FORMATS = frozenset(("date", "date-time", "email", "time", "uri", "uuid"))


class HumanRequestOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: RuntimeSchemaText
    title: str
    description: str | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> str:
        return _normalize_required_text(
            value,
            label="human request option title",
            max_characters=_OPTION_TITLE_MAX_CHARACTERS,
        )

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object | None) -> str | None:
        return normalize_optional_text(
            value,
            label="human request option description",
            max_characters=_OPTION_DESCRIPTION_MAX_CHARACTERS,
        )


class HumanRequestItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: RuntimeSchemaText
    prompt: str
    response_schema: dict[str, JsonValue] | None = None
    options: tuple[HumanRequestOption, ...] | None = Field(
        default=None,
        min_length=2,
        max_length=3,
    )
    allow_other: bool = False
    allow_skip: bool = False

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return _normalize_required_text(
            value,
            label="human request item prompt",
            max_characters=_ITEM_PROMPT_MAX_CHARACTERS,
        )

    @model_validator(mode="after")
    def validate_response_contract(self) -> HumanRequestItem:
        if (self.response_schema is None) == (self.options is None):
            raise ValueError("human request item requires exactly one response_schema or options")
        if self.options is not None:
            option_ids = [option.id for option in self.options]
            if len(option_ids) != len(set(option_ids)):
                raise ValueError("human request item option ids must be unique")
        elif self.allow_other:
            raise ValueError("human request allow_other requires options")
        if self.response_schema is not None:
            _validate_bounded_response_schema(self.response_schema)
            try:
                Draft202012Validator.check_schema(self.response_schema)
            except SchemaError as exc:
                raise ValueError("human request response_schema must be valid JSON Schema") from exc
        return self


class HumanRequestTimeout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    due_at: datetime | None = None
    default_behavior: str | None = None

    @field_validator("default_behavior", mode="before")
    @classmethod
    def normalize_default_behavior(cls, value: object | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_exact_text(
            value,
            label="human request timeout default behavior",
        )
        return normalized if normalized.strip() else None

    @model_validator(mode="after")
    def validate_deadline_policy(self) -> HumanRequestTimeout:
        if self.default_behavior is not None and self.due_at is None:
            raise ValueError("human request default_behavior requires due_at")
        if self.due_at is not None and self.due_at.utcoffset() is None:
            raise ValueError("human request due_at must include a timezone")
        return self


class HumanRequestOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: HumanRequestKind
    summary: str
    items: tuple[HumanRequestItem, ...] = Field(min_length=1, max_length=3)
    files: tuple[FileReference, ...] = ()
    timeout: HumanRequestTimeout | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> str:
        return _normalize_required_text(
            value,
            label="human request summary",
            max_characters=_SUMMARY_MAX_CHARACTERS,
        )

    @model_validator(mode="after")
    def validate_item_ids(self) -> HumanRequestOpenRequest:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("human request item ids must be unique")
        return self

    @field_validator("files")
    @classmethod
    def validate_files(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        return validate_file_reference_limit(files, label="human request")


class HumanRequestOpenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    status: HumanRequestStatus = HumanRequestStatus.OPEN
    must_stop: Literal[True] = True

    @model_validator(mode="after")
    def validate_open_status(self) -> HumanRequestOpenResponse:
        if self.status != HumanRequestStatus.OPEN:
            raise ValueError("human_request_open_response status must be open")
        return self


class PendingHumanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    task_id: TaskIdentifier
    flow_id: RuntimeSchemaText
    assignment_id: RuntimeSchemaText
    attempt_id: RuntimeSchemaText
    summary: str
    kind: HumanRequestKind
    source_dispatch_id: RuntimeSchemaText
    items: tuple[HumanRequestItem, ...] = Field(min_length=1, max_length=3)
    files: tuple[FileReference, ...] = ()
    timeout: HumanRequestTimeout = Field(default_factory=HumanRequestTimeout)
    opened_at: datetime
    status: HumanRequestStatus
    successor_dispatch_id: RuntimeSchemaText | None = None


class HumanRequestValueAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["value"]
    value: JsonValue


class HumanRequestOptionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["option"]
    option_id: RuntimeSchemaText


class HumanRequestOtherAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["other"]
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="human request Other answer",
            is_nonblank_required=True,
        )


class HumanRequestSkippedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["skipped"]


type HumanRequestItemAnswer = Annotated[
    HumanRequestValueAnswer
    | HumanRequestOptionAnswer
    | HumanRequestOtherAnswer
    | HumanRequestSkippedAnswer,
    Field(discriminator="kind"),
]


def serialize_human_request_item_answers(
    item_responses: Mapping[str, HumanRequestItemAnswer] | None,
) -> dict[str, JsonValue] | None:
    if item_responses is None:
        return None
    return {
        item_id: cast(JsonValue, answer.model_dump(mode="json"))
        for item_id, answer in item_responses.items()
    }


class HumanRequestResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    task_id: RuntimeSchemaText
    resolution_kind: HumanRequestResolutionKind
    item_responses: dict[str, HumanRequestItemAnswer] | None = None
    summary: RuntimeSchemaText
    resolved_at: datetime
    resolved_by_actor_ref: RuntimeSchemaText | None = None
    resolved_by_surface: HumanRequestResolutionSurface

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> HumanRequestResolution:
        if self.resolution_kind == HumanRequestResolutionKind.ANSWERED:
            if not self.item_responses:
                raise ValueError("answered human request resolutions require item_responses")
            return self
        if self.item_responses is not None:
            raise ValueError("terminal non-answer resolutions must not include item_responses")
        return self


class HumanRequestResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_responses: dict[RuntimeSchemaText, HumanRequestItemAnswer] = Field(
        min_length=1,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_submitted_response_bounds(self) -> HumanRequestResolveRequest:
        _validate_bounded_json_value(
            self.model_dump(mode="json")["item_responses"],
            label="human request submitted response",
        )
        return self


class HumanRequestResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: RuntimeSchemaText
    resolution: HumanRequestResolution


class HumanRequestRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request: PendingHumanRequest
    resolution: HumanRequestResolution | None = None

    @model_validator(mode="after")
    def validate_resolution_status(self) -> HumanRequestRead:
        if self.request.status == HumanRequestStatus.OPEN and self.resolution is not None:
            raise ValueError("open human requests must not expose a resolution")
        if self.request.status != HumanRequestStatus.OPEN and self.resolution is None:
            raise ValueError("terminal human requests require a resolution")
        return self


def _normalize_required_text(
    value: object,
    *,
    label: str,
    max_characters: int,
) -> str:
    normalized = normalize_exact_text(
        value,
        label=label,
        is_nonblank_required=True,
    )
    if len(normalized) > max_characters:
        raise ValueError(f"{label} exceeds the controller text limit")
    return normalized


def _validate_bounded_json_value(value: object, *, label: str) -> None:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _STRUCTURED_VALUE_MAX_BYTES:
        raise ValueError(f"{label} exceeds the controller byte limit")

    collection_nodes = 0

    def visit(item: object, *, depth: int) -> None:
        nonlocal collection_nodes
        if depth > _STRUCTURED_VALUE_MAX_DEPTH:
            raise ValueError(f"{label} exceeds the controller depth limit")
        if isinstance(item, dict):
            collection_nodes += 1
            for child in item.values():
                visit(child, depth=depth + 1)
        elif isinstance(item, list):
            collection_nodes += 1
            for child in item:
                visit(child, depth=depth + 1)
        if collection_nodes > _STRUCTURED_VALUE_MAX_COLLECTION_NODES:
            raise ValueError(f"{label} exceeds the controller collection limit")

    visit(value, depth=1)


def _validate_bounded_response_schema(schema: dict[str, JsonValue]) -> None:
    _validate_bounded_json_value(
        schema,
        label="human request response_schema",
    )

    def visit(item: object) -> None:
        if isinstance(item, dict):
            reference = item.get("$ref")
            if isinstance(reference, str) and not reference.startswith("#"):
                raise ValueError("human request response_schema forbids remote references")
            if item.get("$dynamicRef") is not None:
                raise ValueError("human request response_schema forbids dynamic references")
            format_name = item.get("format")
            if isinstance(format_name, str) and format_name not in _ALLOWED_SCHEMA_FORMATS:
                raise ValueError("human request response_schema uses an unsupported format")
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(schema)


class HumanRequestListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    items: tuple[HumanRequestRead, ...]


for _human_request_contract in (
    HumanRequestOption,
    HumanRequestItem,
    HumanRequestTimeout,
    HumanRequestOpenRequest,
    HumanRequestOpenResponse,
    PendingHumanRequest,
    HumanRequestValueAnswer,
    HumanRequestOptionAnswer,
    HumanRequestOtherAnswer,
    HumanRequestSkippedAnswer,
    HumanRequestResolution,
    HumanRequestResolveRequest,
    HumanRequestResolveResponse,
    HumanRequestRead,
    HumanRequestListResponse,
):
    _human_request_contract.model_rebuild(_types_namespace=globals())


__all__ = [
    "HumanRequestItem",
    "HumanRequestItemAnswer",
    "HumanRequestListResponse",
    "HumanRequestOpenRequest",
    "HumanRequestOpenResponse",
    "HumanRequestOption",
    "HumanRequestOptionAnswer",
    "HumanRequestOtherAnswer",
    "HumanRequestRead",
    "HumanRequestResolution",
    "HumanRequestResolveRequest",
    "HumanRequestResolveResponse",
    "HumanRequestSkippedAnswer",
    "HumanRequestTimeout",
    "HumanRequestValueAnswer",
    "PendingHumanRequest",
    "serialize_human_request_item_answers",
]

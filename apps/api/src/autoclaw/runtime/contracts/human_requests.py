from __future__ import annotations

from datetime import datetime
from typing import Any

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    SchemaError,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.primitives import (
    HumanRequestKind,
    HumanRequestResolutionKind,
    HumanRequestResolutionSurface,
    HumanRequestStatus,
    TaskIdentifier,
)


class HumanRequestOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: RuntimeSchemaText
    title: RuntimeSchemaText
    description: RuntimeSchemaText | None = None


class HumanRequestContextRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    path: RuntimeSchemaText
    description: RuntimeSchemaText


class HumanRequestItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: RuntimeSchemaText
    prompt: RuntimeSchemaText
    response_schema: dict[str, Any] | None = None
    options: tuple[HumanRequestOption, ...] | None = None

    @model_validator(mode="after")
    def validate_response_contract(self) -> HumanRequestItem:
        if (self.response_schema is None) == (self.options is None):
            raise ValueError("human request item requires exactly one response_schema or options")
        if self.options is not None:
            if not self.options:
                raise ValueError("human request item options must not be empty")
            option_ids = [option.id for option in self.options]
            if len(option_ids) != len(set(option_ids)):
                raise ValueError("human request item option ids must be unique")
        if self.response_schema is not None:
            try:
                Draft202012Validator.check_schema(self.response_schema)
            except SchemaError as exc:
                raise ValueError("human request response_schema must be valid JSON Schema") from exc
        return self


class HumanRequestTimeout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    due_at: datetime | None = None
    default_behavior: RuntimeSchemaText | None = None

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
    summary: RuntimeSchemaText
    items: tuple[HumanRequestItem, ...] = Field(min_length=1, max_length=32)
    context_refs: tuple[HumanRequestContextRef, ...] = Field(default=(), max_length=32)
    timeout: HumanRequestTimeout = Field(default_factory=HumanRequestTimeout)
    suggested_human_instruction: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_item_ids(self) -> HumanRequestOpenRequest:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("human request item ids must be unique")
        return self


class HumanRequestOpenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    task_id: TaskIdentifier
    status: HumanRequestStatus = HumanRequestStatus.OPEN

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
    summary: RuntimeSchemaText
    kind: HumanRequestKind
    source_dispatch_id: RuntimeSchemaText
    items: tuple[HumanRequestItem, ...] = Field(min_length=1, max_length=32)
    context_refs: tuple[HumanRequestContextRef, ...] = Field(default=(), max_length=32)
    timeout: HumanRequestTimeout = Field(default_factory=HumanRequestTimeout)
    suggested_human_instruction: RuntimeSchemaText | None = None
    opened_at: datetime
    status: HumanRequestStatus
    successor_dispatch_id: RuntimeSchemaText | None = None


class HumanRequestResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    request_id: RuntimeSchemaText
    task_id: TaskIdentifier
    resolution_kind: HumanRequestResolutionKind
    item_responses: dict[str, JsonValue] | None = None
    policy_basis: dict[str, JsonValue] | None = None
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

    item_responses: dict[RuntimeSchemaText, JsonValue] = Field(min_length=1, max_length=32)


class HumanRequestResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
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


class HumanRequestListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    items: tuple[HumanRequestRead, ...]


for _human_request_contract in (
    HumanRequestOption,
    HumanRequestContextRef,
    HumanRequestItem,
    HumanRequestTimeout,
    HumanRequestOpenRequest,
    HumanRequestOpenResponse,
    PendingHumanRequest,
    HumanRequestResolution,
    HumanRequestResolveRequest,
    HumanRequestResolveResponse,
    HumanRequestRead,
    HumanRequestListResponse,
):
    _human_request_contract.model_rebuild(_types_namespace=globals())


__all__ = [
    "HumanRequestContextRef",
    "HumanRequestItem",
    "HumanRequestListResponse",
    "HumanRequestOpenRequest",
    "HumanRequestOpenResponse",
    "HumanRequestOption",
    "HumanRequestRead",
    "HumanRequestResolution",
    "HumanRequestResolveRequest",
    "HumanRequestResolveResponse",
    "HumanRequestTimeout",
    "PendingHumanRequest",
]

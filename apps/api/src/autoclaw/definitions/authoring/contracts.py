from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autoclaw.definitions.contracts import DefinitionKind


class DefinitionDraftMode(StrEnum):
    CREATE = "create"
    UPDATE = "update"


class DefinitionDraftStatus(StrEnum):
    CLEAN = "clean"
    MODIFIED = "modified"
    NEW = "new"
    STALE = "stale"
    INVALID = "invalid"


class DefinitionDraftListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class DefinitionDraftBaselineRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    revision_no: int | None = Field(default=None, ge=1)
    content_hash: str | None = None
    source_path: str | None = None


class DefinitionDraftSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: DefinitionKind
    key: str
    mode: DefinitionDraftMode
    draft_path: str
    normalized_path: str
    body_format: Literal["yaml"] = "yaml"
    content_hash: str
    based_on: DefinitionDraftBaselineRead
    status: DefinitionDraftStatus
    updated_at: datetime


class DefinitionDraftDetail(DefinitionDraftSummary):
    body: str
    normalized_content: dict[str, Any] | None = None
    baseline_body: str | None = None
    baseline_normalized_content: dict[str, Any] | None = None
    is_saved: bool = True


class DefinitionDraftListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    items: tuple[DefinitionDraftSummary, ...]
    next_cursor: str | None = None


class DefinitionDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DefinitionKind
    key: str
    mode: DefinitionDraftMode
    body: str | None = None
    body_format: Literal["yaml"] = "yaml"

    @model_validator(mode="after")
    def validate_create_body(self) -> Self:
        if self.mode == DefinitionDraftMode.CREATE and self.body is None:
            raise ValueError("create drafts require body")
        return self


class DefinitionDraftWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    body: str
    body_format: Literal["yaml"] = "yaml"


class DefinitionDraftDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    draft: DefinitionDraftDetail


class DefinitionDraftValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    code: str
    message: str
    path: str | None = None
    kind: Literal["schema", "cross_reference", "stale", "collision"]


class DefinitionDraftValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: DefinitionKind
    key: str
    status: Literal["valid", "invalid", "stale", "name_collision"]
    errors: tuple[DefinitionDraftValidationIssue, ...]
    warnings: tuple[DefinitionDraftValidationIssue, ...]


class DefinitionDraftPublishedRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: DefinitionKind
    key: str
    revision_no: int = Field(ge=1)
    content_hash: str


class DefinitionDraftPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    kind: DefinitionKind
    key: str
    status: Literal["published", "invalid", "stale", "name_collision"]
    published_revision: DefinitionDraftPublishedRevision | None
    validation: DefinitionDraftValidationResponse


__all__ = [
    "DefinitionDraftBaselineRead",
    "DefinitionDraftCreateRequest",
    "DefinitionDraftDetail",
    "DefinitionDraftDetailResponse",
    "DefinitionDraftListQuery",
    "DefinitionDraftListResponse",
    "DefinitionDraftMode",
    "DefinitionDraftPublishResponse",
    "DefinitionDraftPublishedRevision",
    "DefinitionDraftStatus",
    "DefinitionDraftSummary",
    "DefinitionDraftValidationIssue",
    "DefinitionDraftValidationResponse",
    "DefinitionDraftWriteRequest",
]

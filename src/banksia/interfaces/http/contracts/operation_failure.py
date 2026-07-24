from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductFailureCode(StrEnum):
    """Closed, product-safe failure vocabulary shared by HTTP and Operator."""

    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    CURSOR_RESET_REQUIRED = "cursor_reset_required"
    ACCESS_DENIED = "access_denied"
    UNAVAILABLE = "unavailable"
    INTERNAL_ERROR = "internal_error"


class OperationFailure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    is_ok: Literal[False] = Field(default=False, alias="ok")
    code: ProductFailureCode
    summary: str
    is_retryable: bool = Field(alias="retryable")
    field_path: str | None = None
    suggested_next_step: str | None = None

    @property
    def ok(self) -> Literal[False]:
        return self.is_ok

    @property
    def retryable(self) -> bool:
        return self.is_retryable


__all__ = ["OperationFailure", "ProductFailureCode"]

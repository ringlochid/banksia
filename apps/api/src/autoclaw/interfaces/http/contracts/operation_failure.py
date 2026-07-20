from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.runtime.contracts.operation_failure import OperationFailureCode


class OperationFailure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    is_ok: Literal[False] = Field(default=False, alias="ok")
    code: OperationFailureCode
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

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from autoclaw.runtime.contracts.common import RuntimeSchemaText

_WORK_PLAN_STEP_MAX_LENGTH = 512
_WORK_PLAN_EXPLANATION_MAX_LENGTH = 1_024
_VAGUE_TEXT_FINGERPRINTS = frozenset(("", "todo", "tbd"))

_WorkPlanStepText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_WORK_PLAN_STEP_MAX_LENGTH,
    ),
]
_WorkPlanExplanationText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=_WORK_PLAN_EXPLANATION_MAX_LENGTH,
    ),
]


class WorkPlanStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class SetWorkPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step: _WorkPlanStepText
    status: WorkPlanStepStatus

    @field_validator("step")
    @classmethod
    def reject_vague_step(cls, step: str) -> str:
        if _text_fingerprint(step) in _VAGUE_TEXT_FINGERPRINTS:
            raise ValueError("work-plan step must contain meaningful text")
        return step


class SetWorkPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation: _WorkPlanExplanationText | None = None
    steps: tuple[SetWorkPlanStep, ...] = Field(default=(), max_length=9)

    @field_validator("explanation")
    @classmethod
    def reject_vague_explanation(cls, explanation: str | None) -> str | None:
        if explanation is not None and _text_fingerprint(explanation) in _VAGUE_TEXT_FINGERPRINTS:
            raise ValueError("work-plan explanation must contain meaningful text")
        return explanation

    @field_validator("steps")
    @classmethod
    def reject_repeated_steps(
        cls,
        steps: tuple[SetWorkPlanStep, ...],
    ) -> tuple[SetWorkPlanStep, ...]:
        normalized = [step.step.casefold() for step in steps]
        if len(normalized) != len(set(normalized)):
            raise ValueError("work-plan steps must be distinct")
        return steps

    @model_validator(mode="after")
    def allow_at_most_one_in_progress_step(self) -> SetWorkPlanRequest:
        in_progress = sum(step.status == WorkPlanStepStatus.IN_PROGRESS for step in self.steps)
        if in_progress > 1:
            raise ValueError("work plan may contain at most one in_progress step")
        return self


class WorkPlanStepRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    step: _WorkPlanStepText
    status: WorkPlanStepStatus


class WorkPlanRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_id: RuntimeSchemaText
    revision: int = Field(ge=1)
    explanation: _WorkPlanExplanationText | None = None
    steps: tuple[WorkPlanStepRead, ...] = Field(min_length=1, max_length=9)
    authored_by_dispatch_id: RuntimeSchemaText
    updated_at: datetime


class SetWorkPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    changed: bool
    plan: WorkPlanRead | None


def _text_fingerprint(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


__all__ = [
    "SetWorkPlanRequest",
    "SetWorkPlanResponse",
    "SetWorkPlanStep",
    "WorkPlanRead",
    "WorkPlanStepRead",
    "WorkPlanStepStatus",
]

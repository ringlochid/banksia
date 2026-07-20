from pydantic import BaseModel, ConfigDict

from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.refs import AssignmentConsumeRef, CriteriaRef, TransientRef


class AssignmentProduceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: RuntimeSchemaText
    description: RuntimeSchemaText
    file_hint: RuntimeSchemaText | None = None


class AssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: RuntimeSchemaText
    instruction: RuntimeSchemaText | None = None
    criteria: tuple[CriteriaRef, ...] = ()
    consumes: tuple[AssignmentConsumeRef, ...] = ()
    produces: tuple[AssignmentProduceRequirement, ...] = ()
    transient_refs: tuple[TransientRef, ...] = ()


__all__ = ["AssignmentBody", "AssignmentProduceRequirement"]

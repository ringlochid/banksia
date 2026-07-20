from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts.registry import PolicyDefinitionInput, RoleDefinitionInput
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
    WorkflowDefinitionModel,
    WorkflowRevisionModel,
)

DefinitionModelT = TypeVar(
    "DefinitionModelT",
    WorkflowDefinitionModel,
    RoleDefinitionModel,
    PolicyDefinitionModel,
)
RevisionModelT = TypeVar(
    "RevisionModelT",
    WorkflowRevisionModel,
    RoleRevisionModel,
    PolicyRevisionModel,
)
SchemaModelT = TypeVar("SchemaModelT", bound=BaseModel)
DefinitionInput = WorkflowDefinitionInput | RoleDefinitionInput | PolicyDefinitionInput
type DefinitionModelType = (
    type[WorkflowDefinitionModel] | type[RoleDefinitionModel] | type[PolicyDefinitionModel]
)
type RevisionModelType = (
    type[WorkflowRevisionModel] | type[RoleRevisionModel] | type[PolicyRevisionModel]
)
type CurrentDefinitionModel = WorkflowDefinitionModel | RoleDefinitionModel | PolicyDefinitionModel
type CurrentRevisionModel = WorkflowRevisionModel | RoleRevisionModel | PolicyRevisionModel
type CurrentDefinitionRevisionRow = (
    tuple[WorkflowDefinitionModel, WorkflowRevisionModel]
    | tuple[RoleDefinitionModel, RoleRevisionModel]
    | tuple[PolicyDefinitionModel, PolicyRevisionModel]
)


class RegistryWorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    definition: WorkflowDefinitionInput
    revision_no: int = Field(ge=1)


@dataclass(frozen=True)
class PreparedDefinitionRevisionUpsert[DefinitionModelT]:
    definition_row: DefinitionModelT
    revision_no: int
    content_json: dict[str, object]
    content_hash: str
    should_update_current: bool


def model_from_attrs(
    model_type: type[SchemaModelT],
    /,
    **attributes: object,
) -> SchemaModelT:
    return model_type.model_validate(SimpleNamespace(**attributes), from_attributes=True)

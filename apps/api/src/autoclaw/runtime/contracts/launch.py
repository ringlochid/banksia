from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from autoclaw.definitions.compiler.contracts import NormalizedCompiledPlan
from autoclaw.definitions.compiler.role_policy_lookup import MappingRolePolicyLookup
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput
from autoclaw.runtime.contracts.primitives import (
    RuntimeText,
    TaskComposeInput,
    TaskIdentifier,
    TaskRootPaths,
)
from autoclaw.runtime.contracts.projection import AssignmentProjection


class RuntimeBootstrapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskIdentifier
    active_flow_revision_id: RuntimeText
    attempt_id: RuntimeText
    assignment_key: RuntimeText
    task_root: Path
    task_compose: TaskComposeInput
    workflow_definition: WorkflowDefinitionInput
    compiled_plan: NormalizedCompiledPlan
    role_policy_lookup: MappingRolePolicyLookup

    @model_validator(mode="after")
    def validate_workflow_alignment(self) -> RuntimeBootstrapInput:
        if self.task_compose.workflow.key != self.compiled_plan.workflow_key:
            raise ValueError(
                "task compose workflow key "
                f"'{self.task_compose.workflow.key}' does not match compiled plan "
                f"workflow key '{self.compiled_plan.workflow_key}'"
            )
        if self.workflow_definition.id != self.compiled_plan.workflow_key:
            raise ValueError(
                "workflow definition id "
                f"'{self.workflow_definition.id}' does not match compiled plan "
                f"workflow key '{self.compiled_plan.workflow_key}'"
            )
        return self


class RuntimeBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: TaskRootPaths
    assignment: AssignmentProjection


class RuntimeLaunchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskIdentifier
    task_root: Path
    task_compose: TaskComposeInput
    compiler_version: RuntimeText = "runtime-launch"


__all__ = [
    "RuntimeBootstrapInput",
    "RuntimeBootstrapResult",
    "RuntimeLaunchInput",
]

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from banksia.runtime.contracts.primitives import (
    RuntimeText,
    TaskComposeInput,
    TaskIdentifier,
    TaskRootPaths,
)
from banksia.runtime.contracts.projection import AssignmentProjection
from banksia.runtime.launch.legacy_team_adapter import LegacyTeamPlan
from banksia.runtime.team import InitialTaskTeam
from banksia.workflows.contracts import PublishedWorkflowRevision


class RuntimeBootstrapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskIdentifier
    active_flow_revision_id: RuntimeText
    attempt_id: RuntimeText
    assignment_key: RuntimeText
    task_root: Path
    task_compose: TaskComposeInput
    workflow_revision: PublishedWorkflowRevision
    initial_team: InitialTaskTeam
    compiled_plan: LegacyTeamPlan
    max_child_assignments_per_assignment: int = 20
    max_retries_per_assignment: int = 1
    max_wave_members: int = 8

    @model_validator(mode="after")
    def validate_workflow_alignment(self) -> RuntimeBootstrapInput:
        if self.task_compose.workflow.key != self.compiled_plan.workflow_key:
            raise ValueError(
                "task compose workflow key "
                f"'{self.task_compose.workflow.key}' does not match compiled plan "
                f"workflow key '{self.compiled_plan.workflow_key}'"
            )
        if self.workflow_revision.workflow_id != self.compiled_plan.workflow_key:
            raise ValueError(
                "published Workflow id "
                f"'{self.workflow_revision.workflow_id}' does not match legacy plan "
                f"workflow key '{self.compiled_plan.workflow_key}'"
            )
        if self.workflow_revision.revision_no != self.compiled_plan.definition_revision_no:
            raise ValueError("published Workflow revision does not match legacy plan")
        if self.initial_team.team_revision_id != self.compiled_plan.team_revision_id:
            raise ValueError("initial Team does not match legacy plan")
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

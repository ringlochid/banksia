from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from banksia.runtime.contracts.assignment import AssignmentBody
from banksia.runtime.contracts.primitives import RuntimeText, TaskIdentifier, TaskRootPaths
from banksia.runtime.team import InitialTaskTeam
from banksia.workflows.contracts import PublishedWorkflowRevision


class RuntimeBootstrapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskIdentifier
    attempt_id: RuntimeText
    assignment_id: RuntimeText
    task_root: Path
    workspace: Path
    assignment: AssignmentBody
    workflow_revision: PublishedWorkflowRevision
    initial_team: InitialTaskTeam
    max_child_assignments_per_assignment: int = 20
    max_retries_per_assignment: int = 1
    max_wave_members: int = 8


class RuntimeBootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: TaskRootPaths
    assignment: AssignmentBody


class RuntimeLaunchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: TaskIdentifier
    task_root: Path
    workspace: Path
    workflow_revision: PublishedWorkflowRevision
    assignment: AssignmentBody
    max_child_assignments_per_assignment: int = 20
    max_retries_per_assignment: int = 1
    max_wave_members: int = 8


__all__ = ["RuntimeBootstrapInput", "RuntimeBootstrapResult", "RuntimeLaunchInput"]

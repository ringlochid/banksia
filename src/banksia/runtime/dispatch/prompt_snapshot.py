from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.primitives import TaskRootPaths
from banksia.runtime.contracts.prompt import (
    CommandResultTrigger,
    DelegationWaveSettledTrigger,
    DispatchRequestRenderInput,
    HumanResultTrigger,
    OperatorContinueTrigger,
    PromptAssignment,
    PromptContinuation,
    PromptDispatch,
    PromptDynamicInput,
    PromptTask,
    PromptWorkspace,
    SemanticRetryTrigger,
    StructuralReplanTrigger,
    WatchdogRecoveryTrigger,
)
from banksia.runtime.contracts.provider_resolution import ProviderResolution
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.contracts.team_read import (
    CurrentMemberRead,
    DirectTeamMemberRead,
    MemberBehavior,
)
from banksia.runtime.team.reads import (
    available_member_actions,
    effective_capabilities_read,
    resolved_provider_read,
)
from banksia.runtime.work_plan import WorkPlanRead, work_plan_view

type OrdinaryPromptTrigger = (
    DelegationWaveSettledTrigger
    | HumanResultTrigger
    | CommandResultTrigger
    | WatchdogRecoveryTrigger
    | OperatorContinueTrigger
    | StructuralReplanTrigger
)
type RootPromptTrigger = OperatorContinueTrigger


@dataclass(frozen=True, slots=True)
class RootPromptSnapshot:
    task_id: str
    workflow_key: str
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    retry_of_attempt_id: str | None
    team_revision_id: str
    member_id: str
    member_configuration_id: str
    member_branch_basis_id: str
    member_title: str | None
    member_description: str | None
    member_instruction: str | None
    workflow_note: str | None
    assignment_prompt: str
    assignment_files: tuple[FileReference, ...]
    work_plan: WorkPlanRead | None
    capabilities: EffectiveCapabilitySet
    provider: ProviderResolution
    direct_team: tuple[DirectTeamMemberRead, ...]
    paths: TaskRootPaths


@dataclass(frozen=True, slots=True)
class SemanticRetryPromptSnapshot(RootPromptSnapshot):
    is_task_lead: bool
    trigger: SemanticRetryTrigger


@dataclass(frozen=True, slots=True)
class OrdinaryPromptSnapshot(RootPromptSnapshot):
    is_task_lead: bool
    predecessor_dispatch_id: str
    trigger: OrdinaryPromptTrigger


type ContinuationPromptSnapshot = SemanticRetryPromptSnapshot | OrdinaryPromptSnapshot


def build_root_dispatch_request(
    snapshot: RootPromptSnapshot,
    *,
    trigger: RootPromptTrigger | None = None,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(snapshot, trigger=trigger, is_task_lead=True)


def build_delegated_child_dispatch_request(
    snapshot: RootPromptSnapshot,
) -> DispatchRequestRenderInput:
    """Build one initial non-Task-lead child request without a Continuation."""

    return _build_dispatch_request(snapshot, trigger=None, is_task_lead=False)


def build_semantic_retry_dispatch_request(
    snapshot: SemanticRetryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(
        snapshot,
        trigger=snapshot.trigger,
        is_task_lead=snapshot.is_task_lead,
    )


def build_ordinary_dispatch_request(
    snapshot: OrdinaryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(
        snapshot,
        trigger=snapshot.trigger,
        is_task_lead=snapshot.is_task_lead,
    )


def workspace_projection(
    paths: TaskRootPaths,
    *,
    has_workflow_note: bool,
) -> PromptWorkspace:
    task_directory = _relative_workspace_path(paths.task_root, paths.workspace_path)
    return PromptWorkspace(
        root=str(paths.workspace_path),
        task_directory=task_directory,
        manifest=f"{task_directory}/manifest.md",
        workflow_note=(f"{task_directory}/workflow-note.md" if has_workflow_note else None),
        notes=f"{task_directory}/notes",
        artifacts=f"{task_directory}/artifacts",
        command_runs=f"{task_directory}/command-runs",
    )


def _build_dispatch_request(
    snapshot: RootPromptSnapshot,
    *,
    trigger: SemanticRetryTrigger | OrdinaryPromptTrigger | RootPromptTrigger | None,
    is_task_lead: bool,
) -> DispatchRequestRenderInput:
    capabilities = effective_capabilities_read(snapshot.capabilities)
    available_actions = available_member_actions(
        direct_team=snapshot.direct_team,
        capabilities=capabilities,
    )
    return DispatchRequestRenderInput(
        dynamic_input=PromptDynamicInput(
            task=PromptTask(id=snapshot.task_id, workflow_id=snapshot.workflow_key),
            dispatch=PromptDispatch(
                id=snapshot.dispatch_id,
                attempt_id=snapshot.attempt_id,
                assignment_id=snapshot.assignment_id,
            ),
            current_member=CurrentMemberRead(
                id=snapshot.member_id,
                title=snapshot.member_title,
                description=snapshot.member_description or None,
                instruction=snapshot.member_instruction,
                position="task_lead" if is_task_lead else None,
                behavior=(
                    MemberBehavior.MANAGER if snapshot.direct_team else MemberBehavior.CONTRIBUTOR
                ),
                provider=resolved_provider_read(snapshot.provider),
                effective_capabilities=capabilities,
            ),
            assignment=PromptAssignment(
                id=snapshot.assignment_id,
                prompt=snapshot.assignment_prompt,
                files=snapshot.assignment_files,
            ),
            continuation=PromptContinuation(trigger=trigger) if trigger is not None else None,
            direct_team=snapshot.direct_team,
            work_plan=work_plan_view(snapshot.work_plan),
            available_actions=available_actions,
            workspace=workspace_projection(
                snapshot.paths,
                has_workflow_note=bool(snapshot.workflow_note and snapshot.workflow_note.strip()),
            ),
        ),
        member_instruction=snapshot.member_instruction,
        workflow_note=snapshot.workflow_note,
    )


def _relative_workspace_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Task directory must be contained by its workspace") from exc


__all__ = [
    "ContinuationPromptSnapshot",
    "OrdinaryPromptSnapshot",
    "OrdinaryPromptTrigger",
    "RootPromptSnapshot",
    "RootPromptTrigger",
    "SemanticRetryPromptSnapshot",
    "build_delegated_child_dispatch_request",
    "build_ordinary_dispatch_request",
    "build_root_dispatch_request",
    "build_semantic_retry_dispatch_request",
    "workspace_projection",
]

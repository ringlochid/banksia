from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    FlowNodeModel,
)
from banksia.runtime.capabilities import resolve_effective_capabilities_for_node
from banksia.runtime.contracts.capabilities import EffectiveCapabilitySet
from banksia.runtime.contracts.primitives import CapabilityDecision, TaskRootPaths
from banksia.runtime.contracts.prompt import (
    AcceptedBoundaryTrigger,
    ChildReturnTrigger,
    CommandResultTrigger,
    DispatchRequestRenderInput,
    HumanResultTrigger,
    OperatorContinueTrigger,
    PromptAssignment,
    PromptAvailability,
    PromptBehavior,
    PromptContinuation,
    PromptCurrentMember,
    PromptDirectMember,
    PromptDispatch,
    PromptDynamicInput,
    PromptEffectiveCapabilities,
    PromptParticipation,
    PromptProvider,
    PromptSandbox,
    PromptTask,
    PromptWorkspace,
    SemanticRetryTrigger,
    StructuralReplanTrigger,
    WatchdogRecoveryTrigger,
)
from banksia.runtime.contracts.provider_resolution import (
    ClaudeProviderRoute,
    CodexProviderRoute,
    OpenClawProviderRoute,
    ProviderResolution,
)
from banksia.runtime.contracts.refs import FileReference
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.providers import (
    narrow_provider_capabilities,
    resolve_member_provider_route,
)
from banksia.runtime.work_plan import WorkPlanRead, work_plan_view

type BoundaryPromptTrigger = AcceptedBoundaryTrigger | ChildReturnTrigger | SemanticRetryTrigger
type OrdinaryPromptTrigger = (
    HumanResultTrigger
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
    flow_id: str
    flow_revision_id: str
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    retry_of_attempt_id: str | None
    node_key: str
    flow_node_id: str
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
    direct_team: tuple[PromptDirectMember, ...]
    paths: TaskRootPaths


@dataclass(frozen=True, slots=True)
class BoundaryPromptSnapshot(RootPromptSnapshot):
    node_kind: str
    parent_assignment_id: str | None
    predecessor_dispatch_id: str
    trigger: BoundaryPromptTrigger


@dataclass(frozen=True, slots=True)
class OrdinaryPromptSnapshot(RootPromptSnapshot):
    node_kind: str
    parent_assignment_id: str | None
    predecessor_dispatch_id: str
    trigger: OrdinaryPromptTrigger


type ContinuationPromptSnapshot = BoundaryPromptSnapshot | OrdinaryPromptSnapshot


def build_root_dispatch_request(
    snapshot: RootPromptSnapshot,
    *,
    trigger: RootPromptTrigger | None = None,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(snapshot, trigger=trigger, is_task_lead=True)


def build_boundary_dispatch_request(
    snapshot: BoundaryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(
        snapshot,
        trigger=snapshot.trigger,
        is_task_lead=snapshot.node_kind == "root",
    )


def build_ordinary_dispatch_request(
    snapshot: OrdinaryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_dispatch_request(
        snapshot,
        trigger=snapshot.trigger,
        is_task_lead=snapshot.node_kind == "root",
    )


def _build_dispatch_request(
    snapshot: RootPromptSnapshot,
    *,
    trigger: BoundaryPromptTrigger | OrdinaryPromptTrigger | RootPromptTrigger | None,
    is_task_lead: bool,
) -> DispatchRequestRenderInput:
    capabilities = capability_projection(snapshot.capabilities)
    available_actions = _available_actions(
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
            current_member=PromptCurrentMember(
                id=snapshot.member_id,
                title=snapshot.member_title,
                description=snapshot.member_description,
                instruction=snapshot.member_instruction,
                position="task_lead" if is_task_lead else None,
                behavior=(
                    PromptBehavior.MANAGER if snapshot.direct_team else PromptBehavior.CONTRIBUTOR
                ),
                provider=provider_projection(snapshot.provider),
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


async def read_prompt_direct_team(
    session: AsyncSession,
    *,
    children: tuple[FlowNodeModel, ...],
    dependencies: DispatchOpeningDependencies,
) -> tuple[PromptDirectMember, ...]:
    direct_team: list[PromptDirectMember] = []
    for child in children:
        capabilities = await resolve_effective_capabilities_for_node(session, node=child)
        provider = await resolve_member_provider_route(
            session,
            task_id=child.task_id,
            member_configuration_id=child.member_configuration_id,
            settings=dependencies.settings,
            available_adapter_kinds=dependencies.available_adapter_kinds,
        )
        capabilities = narrow_provider_capabilities(
            route=provider.route,
            sandbox=provider.sandbox,
            capabilities=capabilities,
        )
        direct_team.append(
            PromptDirectMember(
                id=child.member_id,
                title=child.member_title,
                description=child.description,
                instruction=child.node_instruction,
                provider=provider_projection(provider),
                capabilities=capability_projection(capabilities),
                participation=(
                    PromptParticipation.SATISFIED
                    if await _has_current_green_participation(session, child)
                    else PromptParticipation.REQUIRED
                ),
                availability=(
                    PromptAvailability.AVAILABLE
                    if child.state in {"ready", "done", "failed"}
                    else PromptAvailability.BUSY
                ),
            )
        )
    return tuple(direct_team)


def capability_projection(
    capabilities: EffectiveCapabilitySet | object,
) -> PromptEffectiveCapabilities:
    allowed_human = tuple(
        kind
        for kind, field_name in (
            ("input", "input"),
            ("direction", "direction"),
            ("approval", "approval"),
            ("review", "review"),
        )
        if _capability_value(
            getattr(
                getattr(capabilities, "human_request", None),
                field_name,
                getattr(capabilities, f"human_{field_name}", "deny"),
            )
        )
        == "allow"
    )
    return PromptEffectiveCapabilities(
        human_request=allowed_human,
        command_run=_capability_value(getattr(capabilities, "command_run", "deny")),
    )


def provider_projection(provider: ProviderResolution) -> PromptProvider:
    route = provider.route
    sandbox = (
        PromptSandbox(
            mode=provider.sandbox.effective_mode.value,
            network=provider.sandbox.effective_network.value,
        )
        if provider.sandbox is not None
        else None
    )
    if isinstance(route, CodexProviderRoute | ClaudeProviderRoute):
        return PromptProvider(
            name=route.kind.value,
            model=route.model_override,
            effort=route.effort_override,
            sandbox=sandbox,
        )
    assert isinstance(route, OpenClawProviderRoute)
    return PromptProvider(
        name=route.kind.value,
        gateway_profile=route.gateway_profile,
    )


def persisted_provider_projection(
    dispatch: DispatchTurnModel,
    capabilities: DispatchCapabilitySetModel,
) -> PromptProvider:
    sandbox = None
    if (
        capabilities.effective_sandbox_mode is not None
        and capabilities.effective_sandbox_network is not None
    ):
        sandbox = PromptSandbox(
            mode=capabilities.effective_sandbox_mode,
            network=capabilities.effective_sandbox_network,
        )
    return PromptProvider(
        name=dispatch.resolved_provider,
        model=dispatch.model_override,
        effort=dispatch.effort_override,
        gateway_profile=dispatch.gateway_profile,
        sandbox=sandbox,
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


def _available_actions(
    *,
    direct_team: tuple[PromptDirectMember, ...],
    capabilities: PromptEffectiveCapabilities,
) -> tuple[str, ...]:
    actions = [
        "get_current_context",
        "set_work_plan",
        "checkpoint",
        "add_child",
    ]
    if direct_team:
        actions.extend(("update_child", "remove_child"))
        if any(member.availability is PromptAvailability.AVAILABLE for member in direct_team):
            actions.append("assign_child")
    if capabilities.human_request:
        actions.append("open_human_request")
    if capabilities.command_run == "allow":
        actions.append("start_command_run")
    return tuple(actions)


async def _has_current_green_participation(
    session: AsyncSession,
    child: FlowNodeModel,
) -> bool:
    if child.current_assignment_id is None:
        return False
    return bool(
        await session.scalar(
            select(
                exists().where(
                    AcceptedBoundaryModel.task_id == child.task_id,
                    AcceptedBoundaryModel.flow_id == child.flow_id,
                    AcceptedBoundaryModel.assignment_id == child.current_assignment_id,
                    AcceptedBoundaryModel.outcome == "green",
                    DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id,
                    DispatchTurnModel.team_revision_id == child.team_revision_id,
                    DispatchTurnModel.member_id == child.member_id,
                    DispatchTurnModel.member_configuration_id == child.member_configuration_id,
                    DispatchTurnModel.member_branch_basis_id == child.member_branch_basis_id,
                )
            )
        )
    )


def _capability_value(value: object) -> str:
    if isinstance(value, CapabilityDecision):
        return value.value
    effective = getattr(value, "effective", value)
    if isinstance(effective, CapabilityDecision):
        return effective.value
    text = str(effective)
    return "allow" if text == "allow" else "deny"


def _relative_workspace_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Task directory must be contained by its workspace") from exc


__all__ = [
    "BoundaryPromptSnapshot",
    "BoundaryPromptTrigger",
    "ContinuationPromptSnapshot",
    "OrdinaryPromptSnapshot",
    "OrdinaryPromptTrigger",
    "RootPromptSnapshot",
    "RootPromptTrigger",
    "build_boundary_dispatch_request",
    "build_ordinary_dispatch_request",
    "build_root_dispatch_request",
    "capability_projection",
    "persisted_provider_projection",
    "provider_projection",
    "read_prompt_direct_team",
    "workspace_projection",
]

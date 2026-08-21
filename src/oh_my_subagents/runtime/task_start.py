from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.session import get_session_factory
from oh_my_subagents.runtime.capabilities import resolve_effective_capabilities_from_member_request
from oh_my_subagents.runtime.contracts import (
    AssignmentBody,
    FileReference,
    RuntimeLaunchInput,
    TaskStartRequest,
    TaskStartResponse,
)
from oh_my_subagents.runtime.contracts.operation_failure import OperationFailureCode
from oh_my_subagents.runtime.dispatch.ordinary_continuation import publish_dispatch_start_due
from oh_my_subagents.runtime.dispatch.preparation import (
    DispatchOpeningDependencies,
    PreparedDispatchRequest,
)
from oh_my_subagents.runtime.errors import RuntimeOperationError
from oh_my_subagents.runtime.file_references import validate_file_references, validate_workspace
from oh_my_subagents.runtime.launch.continuation import stage_initial_root_dispatch
from oh_my_subagents.runtime.launch.service import launch_task_runtime
from oh_my_subagents.runtime.providers import (
    ProviderResolutionError,
    narrow_provider_capabilities,
    provider_selection_from_mapping,
    resolve_provider_route,
    validate_provider_execution_configuration,
)
from oh_my_subagents.runtime.team import plan_initial_task_team
from oh_my_subagents.runtime.workspace.admission import (
    TaskWorkspaceAdmission,
    accept_task_workspace,
    allocate_task_id,
    cleanup_marked_task_workspace,
    recover_task_workspace_admissions,
    stage_task_workspace,
)
from oh_my_subagents.runtime.workspace.storage import WorkspaceIdentity, capture_workspace_identity
from oh_my_subagents.workflows.catalog import read_current_published_workflow
from oh_my_subagents.workflows.contracts import NormalizedMember, PublishedWorkflowRevision
from oh_my_subagents.workflows.service_errors import WorkflowNotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CommittedTaskAdmission:
    task_id: str
    workflow_revision: PublishedWorkflowRevision
    prepared_dispatch: PreparedDispatchRequest
    is_workspace_ready: bool


async def start_task(
    request: TaskStartRequest,
    *,
    session: AsyncSession | None = None,
    dependencies: DispatchOpeningDependencies,
    default_workspace: Path | None = None,
) -> TaskStartResponse:
    """Validate, stage, and atomically admit one Workflow-backed Task."""

    if session is not None:
        return await _start_task(
            session,
            request,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )
    async with get_session_factory()() as owned_session:
        return await _start_task(
            owned_session,
            request,
            dependencies=dependencies,
            default_workspace=default_workspace,
        )


async def _start_task(
    session: AsyncSession,
    request: TaskStartRequest,
    *,
    dependencies: DispatchOpeningDependencies,
    default_workspace: Path | None,
) -> TaskStartResponse:
    workspace = _resolve_workspace(request.workspace, default_workspace=default_workspace)
    files = validate_file_references(workspace, request.files)

    async with dependencies.workspace_admission_coordinator.hold(workspace):
        admission = await _admit_task_in_workspace_lane(
            session,
            request=request,
            workspace=workspace,
            files=files,
            dependencies=dependencies,
        )

    if admission.is_workspace_ready:
        try:
            publish_dispatch_start_due(dependencies, admission.prepared_dispatch)
        except Exception:
            logger.exception(
                "failed to publish committed Task provider-start hint",
                extra={
                    "task_id": admission.task_id,
                    "dispatch_id": admission.prepared_dispatch.dispatch_id,
                },
            )
    return TaskStartResponse(
        task_id=admission.task_id,
        workflow=admission.workflow_revision.workflow_id,
        workflow_revision=admission.workflow_revision.revision_no,
        workspace=workspace,
        manifest=f".banksia/{admission.task_id}/manifest.md",
    )


async def _admit_task_in_workspace_lane(
    session: AsyncSession,
    *,
    request: TaskStartRequest,
    workspace: Path,
    files: tuple[FileReference, ...],
    dependencies: DispatchOpeningDependencies,
) -> _CommittedTaskAdmission:
    try:
        workflow_revision = await read_current_published_workflow(
            session,
            workflow_id=request.workflow,
        )
    except WorkflowNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    _validate_workflow_execution(workflow_revision, dependencies=dependencies)
    assignment = AssignmentBody(prompt=request.prompt, files=files)
    workspace_identity = await asyncio.to_thread(capture_workspace_identity, workspace)
    await recover_task_workspace_admissions(
        session,
        workspaces=(workspace,),
        expected_workspace_identities={workspace: workspace_identity},
        publish_recovered_provider_start=dependencies.post_commit_publisher.publish,
    )
    task_id, workspace_admission = await _stage_task_workspace(
        session,
        workspace=workspace,
        workspace_identity=workspace_identity,
        workflow_revision=workflow_revision,
    )
    prepared = await _stage_initial_task(
        session,
        task_id=task_id,
        workspace=workspace,
        workspace_admission=workspace_admission,
        workflow_revision=workflow_revision,
        assignment=assignment,
        dependencies=dependencies,
    )
    is_workspace_ready = await _commit_task_admission(
        session,
        workspace_admission=workspace_admission,
    )
    return _CommittedTaskAdmission(
        task_id=task_id,
        workflow_revision=workflow_revision,
        prepared_dispatch=prepared,
        is_workspace_ready=is_workspace_ready,
    )


async def _stage_initial_task(
    session: AsyncSession,
    *,
    task_id: str,
    workspace: Path,
    workspace_admission: TaskWorkspaceAdmission,
    workflow_revision: PublishedWorkflowRevision,
    assignment: AssignmentBody,
    dependencies: DispatchOpeningDependencies,
) -> PreparedDispatchRequest:
    runtime_settings = dependencies.settings.runtime
    try:
        await launch_task_runtime(
            session,
            RuntimeLaunchInput(
                task_id=task_id,
                task_root=workspace_admission.task_root,
                workspace=workspace,
                workflow_revision=workflow_revision,
                assignment=assignment,
                max_child_assignments_per_assignment=(
                    runtime_settings.max_child_assignments_per_assignment
                ),
                max_retries_per_assignment=runtime_settings.max_retries_per_assignment,
                max_wave_members=runtime_settings.max_wave_members,
            ),
        )
        return await stage_initial_root_dispatch(
            session,
            task_id=task_id,
            dependencies=dependencies,
        )
    except BaseException:
        try:
            await session.rollback()
        finally:
            cleanup_marked_task_workspace(workspace_admission)
        raise


async def _commit_task_admission(
    session: AsyncSession,
    *,
    workspace_admission: TaskWorkspaceAdmission,
) -> bool:
    try:
        await session.commit()
    except BaseException:
        try:
            await session.rollback()
        except Exception:
            logger.exception(
                "Task commit failed and its session could not be rolled back",
                extra={
                    "task_id": workspace_admission.task_id,
                    "task_root": str(workspace_admission.task_root),
                },
            )
        raise

    try:
        accept_task_workspace(workspace_admission)
    except Exception:
        logger.exception(
            "committed Task retained its initialization marker",
            extra={
                "task_id": workspace_admission.task_id,
                "task_root": str(workspace_admission.task_root),
            },
        )
        return False
    return True


async def _stage_task_workspace(
    session: AsyncSession,
    *,
    workspace: Path,
    workspace_identity: WorkspaceIdentity,
    workflow_revision: PublishedWorkflowRevision,
) -> tuple[str, TaskWorkspaceAdmission]:
    for _ in range(128):
        task_id = await allocate_task_id(session, workspace=workspace)
        initial_team = plan_initial_task_team(workflow_revision, task_id)
        try:
            admission = stage_task_workspace(
                workspace=workspace,
                task_id=task_id,
                workflow_revision=workflow_revision,
                initial_team=initial_team,
                workspace_identity=workspace_identity,
            )
        except FileExistsError:
            continue
        return task_id, admission
    raise RuntimeError("could not reserve a collision-free Task workspace")


def _resolve_workspace(
    requested: Path | None,
    *,
    default_workspace: Path | None,
) -> Path:
    candidate = requested if requested is not None else default_workspace
    if candidate is None:
        raise RuntimeOperationError(
            code=OperationFailureCode.INVALID_TASK_ROOT,
            summary="Task start requires an explicit workspace",
            is_retryable=False,
            suggested_next_step=(
                "Set the controller workspace or resend TaskStartRequest with workspace."
            ),
            status_code_override=422,
        )
    return validate_workspace(candidate)


def _validate_workflow_execution(
    workflow_revision: PublishedWorkflowRevision,
    *,
    dependencies: DispatchOpeningDependencies,
) -> None:
    for member in _walk_members(workflow_revision.workflow.lead):
        try:
            provider = resolve_provider_route(
                provider=provider_selection_from_mapping(
                    member.provider.model_dump(mode="json") if member.provider is not None else None
                ),
                settings=dependencies.settings,
                available_adapter_kinds=dependencies.available_adapter_kinds,
            )
            capabilities = resolve_effective_capabilities_from_member_request(member.capabilities)
            capabilities = narrow_provider_capabilities(
                route=provider.route,
                sandbox=provider.sandbox,
                capabilities=capabilities,
            )
            validate_provider_execution_configuration(
                route=provider.route,
                provider_native_access=capabilities.provider_native_access.effective,
                network_access=capabilities.network_access.effective,
                sandbox_mode=(
                    provider.sandbox.effective_mode if provider.sandbox is not None else None
                ),
            )
        except ProviderResolutionError as exc:
            raise RuntimeOperationError(
                code=OperationFailureCode.ILLEGAL_STATE,
                summary=f"Workflow member {member.id!r} cannot start: {exc}",
                is_retryable=False,
                suggested_next_step=(
                    "Configure an enabled available provider or update the Workflow provider "
                    "selection, then retry Task start."
                ),
                status_code_override=422,
            ) from exc


def _walk_members(root: NormalizedMember) -> tuple[NormalizedMember, ...]:
    members: list[NormalizedMember] = []

    def visit(member: NormalizedMember) -> None:
        members.append(member)
        for child in member.children or ():
            visit(child)

    visit(root)
    return tuple(members)


__all__ = ["start_task"]

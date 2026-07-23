from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import get_settings
from banksia.persistence.session import get_session_factory
from banksia.runtime.contracts import (
    FlowStatus,
    RuntimeLaunchInput,
    TaskStartRequest,
    TaskStartResponse,
    WorkflowManifestRef,
)
from banksia.runtime.flow import WORKFLOW_MANIFEST_REF_DESCRIPTION
from banksia.runtime.ids import compiled_plan_id_for_task, flow_id_for_task, flow_revision_id
from banksia.runtime.launch.service import StagedRuntimeLaunch, launch_task_runtime
from banksia.runtime.node_operations.follow_on import SupportProjectionPublisher
from banksia.runtime.post_commit import FlowStartCommitted, RuntimeEffectPublisher
from banksia.workflows.service_errors import WorkflowNotFoundError

logger = logging.getLogger(__name__)

TASK_COMPOSE_START_BRIDGE_DELETE_AFTER = "WP-03"


async def start_task(
    request: TaskStartRequest,
    *,
    data_dir: Path | None = None,
    session: AsyncSession | None = None,
    runtime_effect_publisher: RuntimeEffectPublisher | None = None,
    support_projection_publisher: SupportProjectionPublisher | None = None,
) -> TaskStartResponse:
    """Commit one Workflow-backed Task through the bounded WP-03 start bridge."""

    task_data_dir = data_dir if data_dir is not None else get_settings().data_dir
    if session is not None:
        return await _start_task(
            session,
            request,
            data_dir=task_data_dir,
            runtime_effect_publisher=runtime_effect_publisher,
            support_projection_publisher=support_projection_publisher,
        )
    async with get_session_factory()() as owned_session:
        return await _start_task(
            owned_session,
            request,
            data_dir=task_data_dir,
            runtime_effect_publisher=runtime_effect_publisher,
            support_projection_publisher=support_projection_publisher,
        )


async def _start_task(
    session: AsyncSession,
    request: TaskStartRequest,
    *,
    data_dir: Path,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
    support_projection_publisher: SupportProjectionPublisher | None,
) -> TaskStartResponse:
    task_id = _mint_task_id(request.task.key)
    try:
        staged_launch = await launch_task_runtime(
            session,
            RuntimeLaunchInput(
                task_id=task_id,
                task_root=data_dir / "tasks" / task_id,
                task_compose=request,
                compiler_version="task-compose-start-bridge",
            ),
        )
        response = _task_start_response(task_id)
        await session.commit()
    except WorkflowNotFoundError as exc:
        await session.rollback()
        raise FileNotFoundError(str(exc)) from exc
    except BaseException:
        await session.rollback()
        raise

    _publish_task_start_follow_on(
        task_id=task_id,
        staged_launch=staged_launch,
        runtime_effect_publisher=runtime_effect_publisher,
        support_projection_publisher=support_projection_publisher,
    )
    return response


def _task_start_response(task_id: str) -> TaskStartResponse:
    return TaskStartResponse(
        task_id=task_id,
        compiled_plan_id=compiled_plan_id_for_task(task_id),
        active_flow_revision_id=flow_revision_id(flow_id_for_task(task_id), 1),
        flow_status=FlowStatus.RUNNING,
        workflow_manifest_ref=WorkflowManifestRef(
            path=Path("_runtime/workflow-manifest.md"),
            description=WORKFLOW_MANIFEST_REF_DESCRIPTION,
        ),
    )


def _publish_task_start_follow_on(
    *,
    task_id: str,
    staged_launch: StagedRuntimeLaunch,
    runtime_effect_publisher: RuntimeEffectPublisher | None,
    support_projection_publisher: SupportProjectionPublisher | None,
) -> None:
    if runtime_effect_publisher is not None:
        runtime_signal = FlowStartCommitted(flow_id_for_task(task_id))
        try:
            runtime_effect_publisher.publish(runtime_signal)
        except Exception:
            logger.exception(
                "failed to publish committed task-start runtime hint",
                extra={"flow_id": runtime_signal.flow_id},
            )
    if support_projection_publisher is None:
        return
    for projection_signal in staged_launch.support_projection_signals:
        try:
            support_projection_publisher.publish(projection_signal)
        except Exception:
            logger.exception(
                "failed to publish committed task-start support-projection hint",
                extra={"support_projection_signal": type(projection_signal).__name__},
            )


def _mint_task_id(task_key: str) -> str:
    normalized_key = re.sub(r"[^a-z0-9]+", "-", task_key.casefold()).strip("-")
    return f"task_{normalized_key or 'task'}_{uuid4().hex[:12]}"


__all__ = ["TASK_COMPOSE_START_BRIDGE_DELETE_AFTER", "start_task"]

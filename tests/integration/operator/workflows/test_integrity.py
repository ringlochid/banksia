from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update

from oh_my_subagents.operator.tools import OperatorTool, OperatorToolName, build_operator_tools
from oh_my_subagents.persistence.models import (
    WorkflowDefinitionModel,
    WorkflowDraftModel,
    WorkflowRevisionModel,
)
from oh_my_subagents.workflows.service_errors import WorkflowIntegrityError
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import AsyncSessionFactory, initialized_workflow_database


def _tool(tools: tuple[OperatorTool, ...], name: OperatorToolName) -> OperatorTool:
    return next(tool for tool in tools if tool.name is name)


def _workflow(workflow_id: str, description: str) -> dict[str, object]:
    return {
        "kind": "workflow",
        "id": workflow_id,
        "description": description,
        "lead": {"id": "lead"},
    }


def _build_tools(
    tmp_path: Path,
    session_factory: AsyncSessionFactory,
) -> tuple[OperatorTool, ...]:
    dependencies = product_dispatch_dependencies(tmp_path)
    return build_operator_tools(
        settings=dependencies.settings,
        session_factory=session_factory,
        dispatch_dependencies=dependencies,
    )


async def _create_draft(
    tools: tuple[OperatorTool, ...],
    *,
    workflow_id: str,
    description: str,
) -> dict[str, Any]:
    return await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_CREATE).call(
        {"workflow": _workflow(workflow_id, description)}
    )


async def _publish_draft(
    tools: tuple[OperatorTool, ...],
    draft: dict[str, Any],
) -> dict[str, Any]:
    return await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_PUBLISH).call(
        {
            "draft_id": draft["draft_id"],
            "etag": draft["etag"],
        }
    )


async def test_corrupt_draft_identity_fails_closed_before_reads_or_mutations(
    tmp_path: Path,
) -> None:
    workflow_id = "draft-identity-owner"
    foreign_id = "foreign-draft-owner"
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = _build_tools(tmp_path, session_factory)
        created = await _create_draft(
            tools,
            workflow_id=workflow_id,
            description="Preserve draft owner identity.",
        )
        draft = created["draft"]
        async with session_factory() as session:
            row = await session.get(WorkflowDraftModel, draft["draft_id"])
            assert row is not None
            corrupt_body = dict(row.content_json)
            corrupt_body["id"] = foreign_id
            await session.execute(
                update(WorkflowDraftModel)
                .where(WorkflowDraftModel.draft_id == row.draft_id)
                .values(content_json=corrupt_body)
            )
            await session.commit()

        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": workflow_id,
                    "selection": {"kind": "catalog"},
                }
            )
        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": workflow_id,
                    "selection": {
                        "kind": "draft",
                        "draft_id": draft["draft_id"],
                        "etag": draft["etag"],
                    },
                }
            )
        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_VALIDATE).call(
                {"draft_id": draft["draft_id"]}
            )
        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_DRAFT_EDIT).call(
                {
                    "draft_id": draft["draft_id"],
                    "etag": draft["etag"],
                    "operation": {
                        "kind": "update_workflow",
                        "patch": {"description": "Must not be accepted."},
                    },
                }
            )
        with pytest.raises(WorkflowIntegrityError):
            await _publish_draft(tools, draft)

        async with session_factory() as session:
            foreign_definition = await session.get(WorkflowDefinitionModel, foreign_id)
            foreign_revisions = await session.scalar(
                select(func.count())
                .select_from(WorkflowRevisionModel)
                .where(WorkflowRevisionModel.workflow_key == foreign_id)
            )

    assert foreign_definition is None
    assert foreign_revisions == 0


async def test_corrupt_published_identity_fails_closed_for_history_and_exact_read(
    tmp_path: Path,
) -> None:
    workflow_id = "published-identity-owner"
    foreign_id = "foreign-published-owner"
    async with initialized_workflow_database(tmp_path) as session_factory:
        tools = _build_tools(tmp_path, session_factory)
        first = await _create_draft(
            tools,
            workflow_id=workflow_id,
            description="First immutable revision.",
        )
        first_publication = await _publish_draft(tools, first["draft"])
        second = await _create_draft(
            tools,
            workflow_id=workflow_id,
            description="Current immutable revision.",
        )
        await _publish_draft(tools, second["draft"])
        async with session_factory() as session:
            revision = await session.scalar(
                select(WorkflowRevisionModel).where(
                    WorkflowRevisionModel.workflow_key == workflow_id,
                    WorkflowRevisionModel.revision_no == first_publication["revision_no"],
                )
            )
            assert revision is not None
            corrupt_body = dict(revision.content_json)
            corrupt_body["id"] = foreign_id
            await session.execute(
                update(WorkflowRevisionModel)
                .where(
                    WorkflowRevisionModel.workflow_key == workflow_id,
                    WorkflowRevisionModel.revision_no == first_publication["revision_no"],
                )
                .values(content_json=corrupt_body)
            )
            await session.commit()

        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": workflow_id,
                    "selection": {
                        "kind": "catalog",
                        "revision_limit": 20,
                    },
                }
            )
        with pytest.raises(WorkflowIntegrityError):
            await _tool(tools, OperatorToolName.WORKFLOW_GET).call(
                {
                    "workflow_id": workflow_id,
                    "selection": {
                        "kind": "published",
                        "revision_no": first_publication["revision_no"],
                    },
                }
            )
        async with session_factory() as session:
            foreign_definition = await session.get(WorkflowDefinitionModel, foreign_id)
            foreign_revisions = await session.scalar(
                select(func.count())
                .select_from(WorkflowRevisionModel)
                .where(WorkflowRevisionModel.workflow_key == foreign_id)
            )

    assert foreign_definition is None
    assert foreign_revisions == 0

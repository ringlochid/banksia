from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    ColumnExpressionArgument,
    case,
    cast,
    exists,
    func,
    literal,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from banksia.persistence.models import (
    WorkflowDefinitionModel,
    WorkflowDraftModel,
)


def workflow_library_ids() -> Subquery:
    active_draft_ids = select(WorkflowDraftModel.workflow_key.label("workflow_id"))
    current_published_ids = select(WorkflowDefinitionModel.workflow_key.label("workflow_id")).where(
        WorkflowDefinitionModel.current_revision_no.is_not(None)
    )
    return active_draft_ids.union(current_published_ids).subquery("workflow_library_ids")


def retired_provider_expression(
    content: ColumnExpressionArgument[dict[str, object]],
    *,
    dialect_name: str,
) -> ColumnElement[bool]:
    if dialect_name == "postgresql":
        return func.coalesce(
            func.jsonb_path_exists(
                cast(content, JSONB),
                literal('$.** ? (@.kind == "openclaw")', type_=JSONPATH),
            ),
            False,
        )
    if dialect_name == "sqlite":
        tree = (
            func.json_tree(cast(content, JSON))
            .table_valued("key", "value")
            .alias("workflow_provider_values")
        )
        return exists(
            select(1).select_from(tree).where(tree.c.key == "kind", tree.c.value == "openclaw")
        )
    raise RuntimeError(f"unsupported Workflow catalog dialect: {dialect_name}")


def visible_workflow_updated_at() -> ColumnElement[datetime]:
    draft_updated_at = WorkflowDraftModel.updated_at
    workflow_updated_at = WorkflowDefinitionModel.updated_at
    return case(
        (draft_updated_at.is_(None), workflow_updated_at),
        (workflow_updated_at.is_(None), draft_updated_at),
        (draft_updated_at >= workflow_updated_at, draft_updated_at),
        else_=workflow_updated_at,
    )


__all__ = [
    "retired_provider_expression",
    "visible_workflow_updated_at",
    "workflow_library_ids",
]

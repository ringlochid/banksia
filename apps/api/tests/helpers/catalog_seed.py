from __future__ import annotations

from datetime import UTC, datetime

from autoclaw.persistence import RuntimeBase
from sqlalchemy import Connection


def seed_catalog(connection: Connection) -> None:
    tables = RuntimeBase.metadata.tables
    timestamp = datetime(2026, 7, 18, tzinfo=UTC)
    connection.execute(
        tables["workflow_definitions"].insert(),
        {
            "workflow_key": "workflow.target",
            "current_revision_no": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    connection.execute(
        tables["workflow_revisions"].insert(),
        {
            "workflow_revision_id": "workflow-revision.target.1",
            "workflow_key": "workflow.target",
            "revision_no": 1,
            "content_hash": "sha256:workflow-target-1",
            "content_json": {},
            "source_path": None,
            "created_at": timestamp,
        },
    )
    connection.execute(tables["workflow_definitions"].update().values(current_revision_no=1))
    connection.execute(
        tables["role_definitions"].insert(),
        {
            "role_key": "role.target",
            "current_revision_no": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    connection.execute(
        tables["role_revisions"].insert(),
        {
            "role_revision_id": "role-revision.target.1",
            "role_key": "role.target",
            "revision_no": 1,
            "content_hash": "sha256:role-target-1",
            "content_json": {},
            "source_path": None,
            "created_at": timestamp,
        },
    )
    connection.execute(tables["role_definitions"].update().values(current_revision_no=1))
    connection.execute(
        tables["policy_definitions"].insert(),
        {
            "policy_key": "policy.target",
            "current_revision_no": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    connection.execute(
        tables["policy_revisions"].insert(),
        {
            "policy_revision_id": "policy-revision.target.1",
            "policy_key": "policy.target",
            "revision_no": 1,
            "content_hash": "sha256:policy-target-1",
            "content_json": {},
            "source_path": None,
            "created_at": timestamp,
        },
    )
    connection.execute(tables["policy_definitions"].update().values(current_revision_no=1))


__all__ = ["seed_catalog"]

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection

from banksia.persistence import RuntimeBase

WORKFLOW_CONTENT_HASH = "1" * 64
WORKFLOW_CONTENT = {
    "kind": "workflow",
    "id": "workflow.target",
    "description": "Target runtime integration fixture.",
    "lead": {
        "id": "root",
        "title": "Root Member",
        "description": "Coordinate target work.",
        "provider": {"kind": "codex"},
        "capabilities": {
            "human_request": ["input", "direction", "approval", "review"],
            "command_run": "allow",
        },
        "children": [
            {
                "id": "child",
                "title": "Child Member",
                "description": "Complete target child work.",
                "provider": {"kind": "codex"},
                "capabilities": {
                    "human_request": ["input", "direction", "approval", "review"],
                    "command_run": "allow",
                },
            }
        ],
    },
}


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
            "content_hash": WORKFLOW_CONTENT_HASH,
            "content_json": WORKFLOW_CONTENT,
            "provenance": "user",
            "source_path": None,
            "created_at": timestamp,
        },
    )
    connection.execute(
        tables["workflow_definitions"]
        .update()
        .where(tables["workflow_definitions"].c.workflow_key == "workflow.target")
        .values(current_revision_no=1)
    )


__all__ = ["WORKFLOW_CONTENT", "WORKFLOW_CONTENT_HASH", "seed_catalog"]

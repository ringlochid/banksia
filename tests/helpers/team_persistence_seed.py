from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import Connection

from banksia.persistence import RuntimeBase
from tests.helpers.catalog_seed import WORKFLOW_CONTENT_HASH


class TeamSeedIds(Protocol):
    @property
    def suffix(self) -> str: ...

    @property
    def task_id(self) -> str: ...


def seed_team(
    connection: Connection,
    *,
    ids: TeamSeedIds,
    timestamp: datetime,
) -> None:
    """Persist the exact two-member Team used by runtime lineage tests."""

    tables = RuntimeBase.metadata.tables
    exact_team_revision_id = team_revision_id(ids)
    for member_id, parent_member_id, _preorder_index in _TEAM_MEMBERS:
        _insert_member_configuration_and_basis(
            connection,
            ids=ids,
            member_id=member_id,
            parent_member_id=parent_member_id,
            timestamp=timestamp,
        )
    _insert_team_revision(connection, ids=ids, timestamp=timestamp)
    for member_id, parent_member_id, preorder_index in _TEAM_MEMBERS:
        connection.execute(
            tables["team_revision_members"].insert(),
            {
                "task_id": ids.task_id,
                "team_revision_id": exact_team_revision_id,
                "member_id": member_id,
                "parent_member_id": parent_member_id,
                "member_configuration_id": member_configuration_id(ids, member_id),
                "member_branch_basis_id": member_branch_basis_id(ids, member_id),
                "preorder_index": preorder_index,
                "sibling_order": 0,
            },
        )
    connection.execute(
        tables["tasks"]
        .update()
        .where(tables["tasks"].c.task_id == ids.task_id)
        .values(current_team_revision_id=exact_team_revision_id)
    )


def team_revision_id(ids: TeamSeedIds) -> str:
    return f"team-revision.{ids.suffix}.1"


def member_configuration_id(ids: TeamSeedIds, member_id: str) -> str:
    return f"member-configuration.{ids.suffix}.{member_id}.1"


def member_branch_basis_id(ids: TeamSeedIds, member_id: str) -> str:
    return f"member-branch-basis.{ids.suffix}.{member_id}.1"


_TEAM_MEMBERS = (("root", None, 0), ("child", "root", 1))


def _insert_member_configuration_and_basis(
    connection: Connection,
    *,
    ids: TeamSeedIds,
    member_id: str,
    parent_member_id: str | None,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["members"].insert(),
        {"task_id": ids.task_id, "member_id": member_id, "created_at": timestamp},
    )
    connection.execute(
        tables["member_configurations"].insert(),
        {
            "member_configuration_id": member_configuration_id(ids, member_id),
            "task_id": ids.task_id,
            "member_id": member_id,
            "predecessor_member_configuration_id": None,
            "title": f"{member_id.title()} Member",
            "description": f"{member_id} member fixture",
            "instruction": None,
            "requested_provider_json": {"kind": "codex"},
            "requested_capabilities_json": {
                "human_request": ["input", "direction", "approval", "review"],
                "command_run": "allow",
            },
            "basis_kind": "workflow_revision",
            "basis_id": f"workflow:workflow.target:1:{WORKFLOW_CONTENT_HASH}",
            "created_at": timestamp,
        },
    )
    connection.execute(
        tables["member_branch_bases"].insert(),
        {
            "member_branch_basis_id": member_branch_basis_id(ids, member_id),
            "task_id": ids.task_id,
            "member_id": member_id,
            "member_configuration_id": member_configuration_id(ids, member_id),
            "parent_member_id": parent_member_id,
            "parent_member_branch_basis_id": (
                member_branch_basis_id(ids, parent_member_id)
                if parent_member_id is not None
                else None
            ),
            "created_at": timestamp,
        },
    )


def _insert_team_revision(
    connection: Connection,
    *,
    ids: TeamSeedIds,
    timestamp: datetime,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["team_revisions"].insert(),
        {
            "team_revision_id": team_revision_id(ids),
            "task_id": ids.task_id,
            "revision_no": 1,
            "predecessor_team_revision_id": None,
            "root_member_id": "root",
            "workflow_key": "workflow.target",
            "workflow_revision_no": 1,
            "workflow_content_hash": WORKFLOW_CONTENT_HASH,
            "provenance_json": {
                "kind": "published_workflow_revision",
                "workflow_id": "workflow.target",
                "revision_no": 1,
                "content_hash": WORKFLOW_CONTENT_HASH,
            },
            "created_at": timestamp,
        },
    )


__all__ = [
    "TeamSeedIds",
    "member_branch_basis_id",
    "member_configuration_id",
    "seed_team",
    "team_revision_id",
]

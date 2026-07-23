from __future__ import annotations

from datetime import datetime
from typing import Protocol

from banksia.persistence import RuntimeBase
from sqlalchemy import Connection

from tests.helpers.team_persistence_seed import (
    TeamSeedIds,
    member_branch_basis_id,
    member_configuration_id,
    team_revision_id,
)


class AssignmentSeedIds(TeamSeedIds, Protocol):
    @property
    def flow_id(self) -> str: ...

    @property
    def flow_revision_id(self) -> str: ...

    @property
    def root_node_id(self) -> str: ...

    @property
    def child_node_id(self) -> str: ...

    @property
    def root_assignment_id(self) -> str: ...

    @property
    def child_assignment_id(self) -> str: ...

    @property
    def root_attempt_id(self) -> str: ...

    @property
    def child_attempt_id(self) -> str: ...


def seed_assignments_and_attempts(
    connection: Connection,
    *,
    ids: AssignmentSeedIds,
    timestamp: datetime,
) -> None:
    """Persist assignment-attempt heads for the two-member lineage fixture."""

    rows = (
        (ids.root_assignment_id, ids.root_node_id, "root", None, ids.root_attempt_id),
        (
            ids.child_assignment_id,
            ids.child_node_id,
            "child",
            ids.root_assignment_id,
            ids.child_attempt_id,
        ),
    )
    for assignment_id, flow_node_id, member_id, parent_assignment_id, attempt_id in rows:
        _insert_assignment_attempt(
            connection,
            ids=ids,
            assignment_id=assignment_id,
            flow_node_id=flow_node_id,
            member_id=member_id,
            parent_assignment_id=parent_assignment_id,
            attempt_id=attempt_id,
            timestamp=timestamp,
        )
    _insert_root_criteria_reference(connection, ids=ids)


def _insert_assignment_attempt(
    connection: Connection,
    *,
    ids: AssignmentSeedIds,
    assignment_id: str,
    flow_node_id: str,
    member_id: str,
    parent_assignment_id: str | None,
    attempt_id: str,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["assignments"].insert(),
        {
            "assignment_id": assignment_id,
            "task_id": ids.task_id,
            "team_revision_id": team_revision_id(ids),
            "member_id": member_id,
            "member_configuration_id": member_configuration_id(ids, member_id),
            "member_branch_basis_id": member_branch_basis_id(ids, member_id),
            "flow_id": ids.flow_id,
            "flow_revision_id": ids.flow_revision_id,
            "flow_node_id": flow_node_id,
            "assignment_key": f"assignment-key.{ids.suffix}.{member_id}",
            "node_key": member_id,
            "parent_assignment_id": parent_assignment_id,
            "summary": f"{member_id} assignment",
            "instruction": None,
            "criteria_json": [],
            "consumes_json": [],
            "produces_json": [],
            "current_attempt_id": None,
            "work_plan_revision": 0,
            "child_assignment_limit": 20,
            "child_assignments_remaining": 20,
            "retry_limit": 1,
            "retries_remaining": 1,
            "created_by_dispatch_id": None,
            "created_at": timestamp,
            "superseded_at": None,
        },
    )
    connection.execute(
        tables["attempts"].insert(),
        {
            "attempt_id": attempt_id,
            "assignment_id": assignment_id,
            "task_id": ids.task_id,
            "flow_id": ids.flow_id,
            "node_key": member_id,
            "retry_of_attempt_id": None,
            "status": "running",
            "terminal_outcome": None,
            "opened_at": timestamp,
            "closed_at": None,
        },
    )
    connection.execute(
        tables["assignments"]
        .update()
        .where(tables["assignments"].c.assignment_id == assignment_id)
        .values(current_attempt_id=attempt_id)
    )
    connection.execute(
        tables["flow_nodes"]
        .update()
        .where(tables["flow_nodes"].c.flow_node_id == flow_node_id)
        .values(current_assignment_id=assignment_id)
    )


def _insert_root_criteria_reference(
    connection: Connection,
    *,
    ids: AssignmentSeedIds,
) -> None:
    connection.execute(
        RuntimeBase.metadata.tables["assignment_criteria_refs"].insert(),
        {
            "assignment_criteria_ref_id": f"criteria-ref.{ids.suffix}.root.0",
            "assignment_id": ids.root_assignment_id,
            "slot": "criteria",
            "logical_path": "_runtime/criteria/root.md",
            "description": "Root criteria.",
            "version": 1,
            "order_index": 0,
        },
    )


__all__ = ["AssignmentSeedIds", "seed_assignments_and_attempts"]

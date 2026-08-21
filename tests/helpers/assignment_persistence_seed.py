from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import Connection

from oh_my_subagents.persistence import RuntimeBase
from tests.helpers.team_persistence_seed import TeamSeedIds


class AssignmentSeedIds(TeamSeedIds, Protocol):
    @property
    def root_member_id(self) -> str: ...

    @property
    def child_member_id(self) -> str: ...

    @property
    def root_assignment_id(self) -> str: ...

    @property
    def child_assignment_id(self) -> str: ...

    @property
    def root_attempt_id(self) -> str: ...

    @property
    def child_attempt_id(self) -> str: ...

    @property
    def root_dispatch_id(self) -> str: ...


def seed_assignments_and_attempts(
    connection: Connection,
    *,
    ids: AssignmentSeedIds,
    timestamp: datetime,
) -> None:
    """Persist assignment-attempt heads for the two-member lineage fixture."""

    rows = (
        (
            ids.root_assignment_id,
            ids.root_member_id,
            None,
            None,
            ids.root_attempt_id,
        ),
        (
            ids.child_assignment_id,
            ids.child_member_id,
            ids.root_assignment_id,
            ids.root_dispatch_id,
            ids.child_attempt_id,
        ),
    )
    for (
        assignment_id,
        member_id,
        parent_assignment_id,
        created_by_dispatch_id,
        attempt_id,
    ) in rows:
        _insert_assignment_attempt(
            connection,
            ids=ids,
            assignment_id=assignment_id,
            member_id=member_id,
            parent_assignment_id=parent_assignment_id,
            created_by_dispatch_id=created_by_dispatch_id,
            attempt_id=attempt_id,
            timestamp=timestamp,
        )


def _insert_assignment_attempt(
    connection: Connection,
    *,
    ids: AssignmentSeedIds,
    assignment_id: str,
    member_id: str,
    parent_assignment_id: str | None,
    created_by_dispatch_id: str | None,
    attempt_id: str,
    timestamp: datetime,
) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["assignments"].insert(),
        {
            "assignment_id": assignment_id,
            "task_id": ids.task_id,
            "member_id": member_id,
            "parent_assignment_id": parent_assignment_id,
            "prompt": f"Complete the {member_id} assignment.",
            "current_attempt_id": None,
            "work_plan_revision": 0,
            "child_assignment_limit": 20,
            "child_assignments_remaining": 20,
            "retry_limit": 1,
            "retries_remaining": 1,
            "created_by_dispatch_id": created_by_dispatch_id,
            "created_at": timestamp,
            "terminal_outcome": None,
            "closed_at": None,
        },
    )
    connection.execute(
        tables["attempts"].insert(),
        {
            "attempt_id": attempt_id,
            "assignment_id": assignment_id,
            "task_id": ids.task_id,
            "retry_of_attempt_id": None,
            "current_dispatch_id": None,
            "current_wait_id": None,
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


__all__ = ["AssignmentSeedIds", "seed_assignments_and_attempts"]

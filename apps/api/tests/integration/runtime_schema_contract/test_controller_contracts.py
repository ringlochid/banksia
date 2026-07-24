from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from banksia.persistence import RuntimeBase
from sqlalchemy import Connection, func, select
from sqlalchemy.exc import IntegrityError
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)

NOW = datetime(2026, 7, 18, tzinfo=UTC)
Mutation = Callable[[Connection, dict[str, RuntimeIds]], None]


def _assert_rejected(
    tmp_path: Path,
    mutation: Mutation,
    *,
    suffixes: tuple[str, ...] = ("a",),
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            scopes = {suffix: seed_runtime_scope(connection, suffix=suffix) for suffix in suffixes}
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                mutation(connection, scopes)
    finally:
        engine.dispose()


def test_source_dispatch_preserves_terminal_checkpoint_supersession_history(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                RuntimeBase.metadata.tables["attempt_checkpoints"].insert(),
                {
                    "checkpoint_id": "checkpoint.a.root.superseding-terminal",
                    "task_id": ids.task_id,
                    "flow_id": ids.flow_id,
                    "assignment_id": ids.root_assignment_id,
                    "attempt_id": ids.root_attempt_id,
                    "authoring_dispatch_id": ids.root_dispatch_id,
                    "outcome": "blocked",
                    "summary": "A superseding terminal checkpoint.",
                    "details": "The later exact message remains in history.",
                    "recorded_at": NOW,
                },
            )
        with engine.connect() as connection:
            terminal_count = connection.scalar(
                select(func.count())
                .select_from(RuntimeBase.metadata.tables["attempt_checkpoints"])
                .where(
                    RuntimeBase.metadata.tables["attempt_checkpoints"].c.authoring_dispatch_id
                    == ids.root_dispatch_id,
                    RuntimeBase.metadata.tables["attempt_checkpoints"].c.outcome.is_not(None),
                )
            )
        assert terminal_count == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("table_name", ("flow_nodes", "node_plan_revisions"))
def test_active_node_provider_kind_rejects_unknown_values(
    tmp_path: Path,
    table_name: str,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        table = RuntimeBase.metadata.tables[table_name]
        connection.execute(
            table.update()
            .where(table.c.flow_node_id == ids.root_node_id)
            .values(provider_kind="unknown-provider")
        )

    _assert_rejected(tmp_path, mutate)


@pytest.mark.parametrize("axis", ("child_assignment", "retry"))
@pytest.mark.parametrize(
    ("limit", "remaining"),
    (
        (1, None),
        (None, 1),
        (-1, 0),
        (1, -1),
        (1, 2),
    ),
)
def test_assignment_budget_rejects_inconsistent_or_out_of_range_pairs(
    tmp_path: Path,
    axis: str,
    limit: int | None,
    remaining: int | None,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        assignments = RuntimeBase.metadata.tables["assignments"]
        values = (
            {
                "child_assignment_limit": limit,
                "child_assignments_remaining": remaining,
            }
            if axis == "child_assignment"
            else {
                "retry_limit": limit,
                "retries_remaining": remaining,
            }
        )
        connection.execute(
            assignments.update()
            .where(assignments.c.assignment_id == ids.root_assignment_id)
            .values(**values)
        )

    _assert_rejected(tmp_path, mutate)


def test_assignment_budget_accepts_bounded_remaining_values(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            assignments = RuntimeBase.metadata.tables["assignments"]
            connection.execute(
                assignments.update()
                .where(assignments.c.assignment_id == ids.root_assignment_id)
                .values(
                    child_assignment_limit=3,
                    child_assignments_remaining=2,
                    retry_limit=1,
                    retries_remaining=0,
                )
            )
        with engine.connect() as connection:
            assignment = connection.execute(
                select(assignments).where(assignments.c.assignment_id == ids.root_assignment_id)
            ).one()
        assert assignment.child_assignments_remaining == 2
        assert assignment.retries_remaining == 0
    finally:
        engine.dispose()


def test_attempt_latest_checkpoint_pointer_accepts_only_the_exact_attempt(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            attempts = RuntimeBase.metadata.tables["attempts"]
            connection.execute(
                attempts.update()
                .where(attempts.c.attempt_id == ids.root_attempt_id)
                .values(latest_checkpoint_id=ids.root_checkpoint_id)
            )
        with engine.connect() as connection:
            attempt = connection.execute(
                select(attempts).where(attempts.c.attempt_id == ids.root_attempt_id)
            ).one()
        assert attempt.latest_checkpoint_id == ids.root_checkpoint_id
    finally:
        engine.dispose()

    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        attempts = RuntimeBase.metadata.tables["attempts"]
        connection.execute(
            attempts.update()
            .where(attempts.c.attempt_id == ids.child_attempt_id)
            .values(latest_checkpoint_id=ids.root_checkpoint_id)
        )

    invalid_path = tmp_path / "invalid-pointer"
    invalid_path.mkdir()
    _assert_rejected(invalid_path, mutate)


def test_checkpoint_file_references_are_ordered_owner_scoped_values(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                RuntimeBase.metadata.tables["checkpoint_file_references"].insert(),
                [
                    {
                        "checkpoint_id": ids.root_checkpoint_id,
                        "order_index": 0,
                        "path": "notes/approach.md",
                        "description": "Working approach.",
                    },
                    {
                        "checkpoint_id": ids.root_checkpoint_id,
                        "order_index": 1,
                        "path": "artifacts/report.md",
                        "description": "Reviewable report.",
                    },
                ],
            )
        with engine.connect() as connection:
            rows = connection.execute(
                select(RuntimeBase.metadata.tables["checkpoint_file_references"]).order_by(
                    RuntimeBase.metadata.tables["checkpoint_file_references"].c.order_index
                )
            ).all()
        assert [(row.path, row.description) for row in rows] == [
            ("notes/approach.md", "Working approach."),
            ("artifacts/report.md", "Reviewable report."),
        ]
    finally:
        engine.dispose()


def test_checkpoint_file_reference_rejects_duplicate_owner_path(
    tmp_path: Path,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        references = RuntimeBase.metadata.tables["checkpoint_file_references"]
        connection.execute(
            references.insert(),
            [
                {
                    "checkpoint_id": ids.root_checkpoint_id,
                    "order_index": 0,
                    "path": "artifacts/report.md",
                    "description": None,
                },
                {
                    "checkpoint_id": ids.root_checkpoint_id,
                    "order_index": 1,
                    "path": "artifacts/report.md",
                    "description": "Duplicate path.",
                },
            ],
        )

    _assert_rejected(tmp_path, mutate)


def test_work_plan_rejects_more_than_one_in_progress_step(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        assignments = RuntimeBase.metadata.tables["assignments"]
        connection.execute(
            assignments.update()
            .where(assignments.c.assignment_id == ids.root_assignment_id)
            .values(work_plan_revision=1)
        )
        connection.execute(
            RuntimeBase.metadata.tables["assignment_work_plans"].insert(),
            {
                "assignment_id": ids.root_assignment_id,
                "revision": 1,
                "explanation": "Target plan",
                "authoring_dispatch_id": ids.current_dispatch_id,
                "committed_at": NOW,
            },
        )
        steps = RuntimeBase.metadata.tables["assignment_work_plan_steps"]
        connection.execute(
            steps.insert(),
            [
                {
                    "work_plan_step_id": "plan-step.1",
                    "assignment_id": ids.root_assignment_id,
                    "order_index": 0,
                    "step": "First",
                    "status": "in_progress",
                },
                {
                    "work_plan_step_id": "plan-step.2",
                    "assignment_id": ids.root_assignment_id,
                    "order_index": 1,
                    "step": "Second",
                    "status": "in_progress",
                },
            ],
        )

    _assert_rejected(tmp_path, mutate)

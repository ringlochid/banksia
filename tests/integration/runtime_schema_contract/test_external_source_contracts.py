from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.exc import IntegrityError

from banksia.persistence import RuntimeBase
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


def _assert_rejected(tmp_path: Path, mutation: Mutation) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            scopes = {"a": seed_runtime_scope(connection)}
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                mutation(connection, scopes)
    finally:
        engine.dispose()


def test_human_request_open_and_answer_shapes_are_database_validated(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            requests = RuntimeBase.metadata.tables["human_requests"]
            connection.execute(requests.insert(), _open_human_request(ids))
            connection.execute(
                requests.update()
                .where(requests.c.request_id == "human-request.target")
                .values(
                    status="resolved",
                    resolution_kind="answered",
                    item_responses_json={
                        "choice": {
                            "kind": "option",
                            "option_id": "approve",
                        }
                    },
                    resolution_summary="Approved by the local operator.",
                    resolved_by_actor_ref="operator.local",
                    resolved_by_surface="control_ui",
                    resolved_at=NOW + timedelta(minutes=1),
                )
            )
        with engine.connect() as connection:
            request = connection.execute(
                select(RuntimeBase.metadata.tables["human_requests"])
            ).one()
        assert request.status == "resolved"
        assert request.resolution_kind == "answered"
    finally:
        engine.dispose()


def test_human_request_timeout_requires_an_immutable_timeout_policy(
    tmp_path: Path,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _open_human_request(scopes["a"])
        row["due_at"] = NOW + timedelta(minutes=5)
        connection.execute(RuntimeBase.metadata.tables["human_requests"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_human_request_cannot_time_out_without_a_deadline(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _open_human_request(scopes["a"])
        row.update(
            status="timed_out",
            resolution_kind="timed_out",
            resolution_policy_basis_json={"behavior": "continue"},
            resolution_summary="Timed out.",
            resolved_by_surface="controller",
            resolved_at=NOW,
        )
        connection.execute(RuntimeBase.metadata.tables["human_requests"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_human_request_successor_must_continue_its_exact_source_dispatch(
    tmp_path: Path,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        row = _open_human_request(ids)
        row.update(
            request_id="human-request.invalid-successor",
            status="resolved",
            resolution_kind="answered",
            item_responses_json={
                "choice": {
                    "kind": "option",
                    "option_id": "approve",
                }
            },
            resolution_summary="Answered.",
            resolved_by_surface="control_api",
            successor_dispatch_id=ids.root_dispatch_id,
            resolved_at=NOW,
        )
        connection.execute(RuntimeBase.metadata.tables["human_requests"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_command_run_lifecycle_requires_complete_terminal_provenance(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            runs = RuntimeBase.metadata.tables["command_runs"]
            connection.execute(runs.insert(), _pending_command_run(ids))
            connection.execute(
                runs.update()
                .where(runs.c.run_id == "c_01234567")
                .values(
                    state="running",
                    ownership_revision=1,
                    started_at=NOW + timedelta(seconds=1),
                )
            )
            connection.execute(
                runs.update()
                .where(runs.c.run_id == "c_01234567")
                .values(
                    state="succeeded",
                    terminal_summary="Command completed.",
                    terminal_exit_code=0,
                    terminal_event_source="process_owner",
                    ended_at=NOW + timedelta(seconds=2),
                )
            )
        with engine.connect() as connection:
            run = connection.execute(select(RuntimeBase.metadata.tables["command_runs"])).one()
        assert run.state == "succeeded"
        assert run.terminal_event_source == "process_owner"
    finally:
        engine.dispose()


def test_command_timeout_deadline_begins_only_after_process_start(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            runs = RuntimeBase.metadata.tables["command_runs"]
            row = _pending_command_run(ids)
            row["timeout_seconds"] = 60
            connection.execute(runs.insert(), row)
            connection.execute(
                runs.update()
                .where(runs.c.run_id == "c_01234567")
                .values(
                    state="running",
                    ownership_revision=1,
                    started_at=NOW + timedelta(seconds=1),
                    due_at=NOW + timedelta(seconds=61),
                )
            )
        with engine.connect() as connection:
            run = connection.execute(select(RuntimeBase.metadata.tables["command_runs"])).one()
        assert run.started_at == NOW + timedelta(seconds=1)
        assert run.due_at == NOW + timedelta(seconds=61)
    finally:
        engine.dispose()


def test_started_command_with_timeout_requires_a_deadline(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _pending_command_run(scopes["a"])
        row.update(
            state="running",
            timeout_seconds=60,
            started_at=NOW,
        )
        connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)

    _assert_rejected(tmp_path, mutate)


@pytest.mark.parametrize("failure_code", [None, "process_not_found"])
def test_abandoned_command_requires_ownership_lost_diagnostic(
    tmp_path: Path,
    failure_code: str | None,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _pending_command_run(scopes["a"])
        row.update(
            state="abandoned",
            started_at=NOW - timedelta(seconds=1),
            ended_at=NOW,
            terminal_summary="Command ownership was lost during restart.",
            terminal_failure_code=failure_code,
            terminal_event_source="controller",
        )
        connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_abandoned_command_accepts_exact_ownership_lost_diagnostic(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            row = _pending_command_run(ids)
            row.update(
                state="abandoned",
                started_at=NOW - timedelta(seconds=1),
                ended_at=NOW,
                terminal_summary="Command ownership was lost during restart.",
                terminal_failure_code="command_ownership_lost",
                terminal_event_source="controller",
            )
            connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)
        with engine.connect() as connection:
            run = connection.execute(select(RuntimeBase.metadata.tables["command_runs"])).one()
        assert run.state == "abandoned"
        assert run.terminal_failure_code == "command_ownership_lost"
    finally:
        engine.dispose()


def test_command_cancellation_request_requires_owner_timestamp(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _pending_command_run(scopes["a"])
        row["state"] = "cancellation_requested"
        connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_command_run_cannot_time_out_without_a_deadline(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        row = _pending_command_run(scopes["a"])
        row.update(
            state="timed_out",
            terminal_summary="Timed out.",
            terminal_event_source="process_owner",
            ended_at=NOW,
        )
        connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def test_command_successor_must_continue_its_exact_source_dispatch(
    tmp_path: Path,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        row = _pending_command_run(ids)
        row.update(
            run_id="c_76543210",
            state="succeeded",
            terminal_summary="Completed.",
            terminal_exit_code=0,
            terminal_event_source="process_owner",
            successor_dispatch_id=ids.root_dispatch_id,
            ended_at=NOW,
        )
        connection.execute(RuntimeBase.metadata.tables["command_runs"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def _open_human_request(ids: RuntimeIds) -> dict[str, object]:
    return {
        "request_id": "human-request.target",
        "task_id": ids.task_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": ids.current_dispatch_id,
        "request_kind": "approval",
        "request_summary": "Approve the target transition.",
        "request_items_json": [
            {
                "id": "choice",
                "prompt": "Approve?",
                "options": [
                    {"id": "approve", "title": "Approve"},
                    {"id": "reject", "title": "Reject"},
                ],
            }
        ],
        "capability_basis_json": {"human_approval": "allow"},
        "due_at": None,
        "timeout_policy_json": None,
        "default_behavior_json": None,
        "status": "open",
        "resolution_kind": None,
        "item_responses_json": None,
        "resolution_policy_basis_json": None,
        "resolution_summary": None,
        "resolved_by_actor_ref": None,
        "resolved_by_surface": None,
        "successor_dispatch_id": None,
        "opened_at": NOW,
        "resolved_at": None,
    }


def _pending_command_run(ids: RuntimeIds) -> dict[str, object]:
    return {
        "run_id": "c_01234567",
        "task_id": ids.task_id,
        "assignment_id": ids.root_assignment_id,
        "attempt_id": ids.root_attempt_id,
        "source_dispatch_id": ids.current_dispatch_id,
        "command_spec_json": {"argv": ["true"]},
        "cwd_policy_json": None,
        "summary": "Run a target command.",
        "timeout_seconds": None,
        "due_at": None,
        "output_path": f".banksia/{ids.task_id}/command-runs/c_01234567/output.log",
        "output_observed_bytes": 0,
        "output_written_bytes": 0,
        "output_complete": False,
        "output_encoding": "raw_bytes",
        "state": "pending_start",
        "ownership_revision": 0,
        "process_metadata_json": None,
        "cancellation_requested_at": None,
        "cancellation_requested_by_actor_ref": None,
        "terminal_summary": None,
        "terminal_exit_code": None,
        "terminal_failure_code": None,
        "terminal_event_source": None,
        "terminal_actor_ref": None,
        "successor_dispatch_id": None,
        "created_at": NOW,
        "started_at": None,
        "ended_at": None,
    }

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from banksia.persistence import RuntimeBase
from sqlalchemy import Connection, select
from sqlalchemy.exc import IntegrityError
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    member_branch_basis_id,
    member_configuration_id,
    seed_runtime_scope,
    team_revision_id,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)

Mutation = Callable[[Connection, dict[str, RuntimeIds]], None]
NOW = datetime(2026, 7, 18, tzinfo=UTC)


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


def test_flow_start_source_cannot_consume_another_flows_root(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        sources = RuntimeBase.metadata.tables["flow_start_sources"]
        connection.execute(
            sources.update()
            .where(sources.c.flow_id == scopes["a"].flow_id)
            .values(successor_dispatch_id=scopes["b"].root_dispatch_id)
        )

    _assert_rejected(tmp_path, mutate, suffixes=("a", "b"))


def test_boundary_decision_must_belong_to_the_same_source_dispatch(
    tmp_path: Path,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        assignments = RuntimeBase.metadata.tables["assignments"]
        connection.execute(
            assignments.update()
            .where(assignments.c.assignment_id == ids.child_assignment_id)
            .values(created_by_dispatch_id=ids.root_dispatch_id)
        )
        connection.execute(
            RuntimeBase.metadata.tables["assignment_decisions"].insert(),
            {
                "assignment_decision_id": "decision.root-staged-child",
                "source_dispatch_id": ids.root_dispatch_id,
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "assignment_id": ids.root_assignment_id,
                "attempt_id": ids.root_attempt_id,
                "source_flow_revision_id": ids.flow_revision_id,
                "decision_kind": "staged_child",
                "staged_child_assignment_id": ids.child_assignment_id,
                "staged_child_attempt_id": ids.child_attempt_id,
                "recorded_at": NOW,
            },
        )
        connection.execute(
            RuntimeBase.metadata.tables["accepted_boundaries"].insert(),
            {
                "accepted_boundary_id": "boundary.invalid-decision-source",
                "source_dispatch_id": ids.child_dispatch_id,
                "task_id": ids.task_id,
                "flow_id": ids.flow_id,
                "assignment_id": ids.child_assignment_id,
                "attempt_id": ids.child_attempt_id,
                "outcome": "yield",
                "checkpoint_id": None,
                "assignment_decision_id": "decision.root-staged-child",
                "successor_dispatch_id": None,
                "committed_at": NOW,
            },
        )

    _assert_rejected(tmp_path, mutate)


def test_dispatch_node_must_belong_to_its_assignment(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        connection.execute(
            RuntimeBase.metadata.tables["dispatch_turns"].insert(),
            _closed_successor_row(
                ids,
                dispatch_id="dispatch.invalid-assignment-node",
                node_key="child",
            ),
        )

    _assert_rejected(tmp_path, mutate)


@pytest.mark.parametrize(
    ("table_name", "where_column", "where_value"),
    (
        ("compiled_plan_nodes", "compiled_plan_id", "compiled-plan.a"),
        ("flow_nodes", "flow_node_id", "flow-node.a.root"),
        ("node_plan_revisions", "flow_node_id", "flow-node.a.root"),
    ),
)
@pytest.mark.parametrize(
    "team_selection_field",
    (
        "team_revision_id",
        "member_id",
        "member_configuration_id",
        "member_branch_basis_id",
    ),
)
def test_runtime_node_exact_team_selection_is_required(
    tmp_path: Path,
    table_name: str,
    where_column: str,
    where_value: str,
    team_selection_field: str,
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        del scopes
        table = RuntimeBase.metadata.tables[table_name]
        connection.execute(
            table.update()
            .where(table.c[where_column] == where_value)
            .values({team_selection_field: None})
        )

    _assert_rejected(tmp_path, mutate)


def test_workflow_revision_numbers_are_positive(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        del scopes
        tables = RuntimeBase.metadata.tables
        workflow_key = "workflow.invalid-revision"
        connection.execute(
            tables["workflow_definitions"].insert(),
            {
                "workflow_key": workflow_key,
                "current_revision_no": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        connection.execute(
            tables["workflow_revisions"].insert(),
            {
                "workflow_revision_id": "workflow-revision.invalid",
                "workflow_key": workflow_key,
                "revision_no": 0,
                "content_hash": "0" * 64,
                "content_json": {},
                "provenance": "user",
                "source_path": None,
                "created_at": NOW,
            },
        )

    _assert_rejected(tmp_path, mutate)


def test_required_json_contracts_reject_python_none(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        compiled_plans = RuntimeBase.metadata.tables["compiled_plans"]
        connection.execute(
            compiled_plans.update()
            .where(compiled_plans.c.compiled_plan_id == ids.compiled_plan_id)
            .values(snapshot_json=None)
        )

    _assert_rejected(tmp_path, mutate)


def test_closed_dispatch_candidates_cannot_duplicate_one_successor(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                dispatches.insert(),
                _closed_successor_row(
                    ids,
                    dispatch_id="dispatch.closed-successor.first",
                ),
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    dispatches.insert(),
                    _closed_successor_row(
                        ids,
                        dispatch_id="dispatch.closed-successor.second",
                    ),
                )

        with engine.connect() as connection:
            committed_successors = tuple(
                connection.execute(
                    select(
                        dispatches.c.dispatch_id,
                        dispatches.c.active_status_marker,
                    ).where(dispatches.c.predecessor_dispatch_id == ids.current_dispatch_id)
                )
            )
    finally:
        engine.dispose()

    assert committed_successors == (("dispatch.closed-successor.first", None),)


def test_current_starting_dispatch_closes_with_attempt_authority_clear(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
    attempts = RuntimeBase.metadata.tables["attempts"]
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
            connection.execute(
                dispatches.update()
                .where(dispatches.c.dispatch_id == ids.current_dispatch_id)
                .values(
                    status="starting",
                    adapter_started_at=None,
                    last_node_activity_at=None,
                    next_provider_start_at=NOW,
                    provider_start_retry_kind="initial",
                )
            )

        with engine.begin() as connection:
            connection.execute(
                dispatches.update()
                .where(
                    dispatches.c.dispatch_id == ids.current_dispatch_id,
                    dispatches.c.status == "starting",
                    dispatches.c.adapter_started_at.is_(None),
                )
                .values(
                    status="closed",
                    next_provider_start_at=None,
                    provider_start_retry_kind=None,
                    closed_at=NOW,
                    closed_reason="boundary",
                )
            )
            connection.execute(
                attempts.update()
                .where(attempts.c.attempt_id == ids.root_attempt_id)
                .values(current_dispatch_id=None)
            )

        with engine.connect() as connection:
            dispatch = connection.execute(
                select(dispatches).where(dispatches.c.dispatch_id == ids.current_dispatch_id)
            ).one()
            attempt_dispatch_id = connection.scalar(
                select(attempts.c.current_dispatch_id).where(
                    attempts.c.attempt_id == ids.root_attempt_id
                )
            )
    finally:
        engine.dispose()

    assert dispatch.status == "closed"
    assert dispatch.adapter_started_at is None
    assert dispatch.closed_reason == "boundary"
    assert attempt_dispatch_id is None


def test_watchdog_close_is_illegal_before_provider_acceptance(tmp_path: Path) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        row = _closed_successor_row(ids, dispatch_id="dispatch.invalid-starting-watchdog")
        row.update(
            adapter_started_at=None,
            last_node_activity_at=None,
            closed_reason="watchdog_superseded",
        )
        connection.execute(RuntimeBase.metadata.tables["dispatch_turns"].insert(), row)

    _assert_rejected(tmp_path, mutate)


@pytest.mark.parametrize(
    "route_updates",
    (
        {"model_override": ""},
        {"effort_override": "   "},
        {"model_source": "member_configuration"},
        {"effort_source": "member_configuration"},
        {
            "model_override": "authored",
            "model_source": "member_configuration",
            "provider_selection_basis": "default",
        },
        {
            "requested_provider": "openclaw",
            "resolved_provider": "openclaw",
            "provider_route_kind": "openclaw",
            "gateway_profile": "",
        },
        {"gateway_profile": "unexpected"},
        {
            "requested_provider": "openclaw",
            "resolved_provider": "openclaw",
            "provider_route_kind": "openclaw",
            "gateway_profile": "default",
            "model_override": "unexpected",
        },
    ),
    ids=(
        "empty-model-override",
        "blank-effort-override",
        "authored-model-source-without-value",
        "authored-effort-source-without-value",
        "authored-field-source-on-default-provider",
        "empty-gateway-profile",
        "gateway-field-on-codex",
        "model-field-on-openclaw",
    ),
)
def test_dispatch_route_is_a_strict_nonempty_variant(
    tmp_path: Path,
    route_updates: dict[str, object],
) -> None:
    def mutate(connection: Connection, scopes: dict[str, RuntimeIds]) -> None:
        ids = scopes["a"]
        row = _closed_successor_row(ids, dispatch_id="dispatch.invalid-provider-route")
        row.update(route_updates)
        connection.execute(RuntimeBase.metadata.tables["dispatch_turns"].insert(), row)

    _assert_rejected(tmp_path, mutate)


def _closed_successor_row(
    ids: RuntimeIds,
    *,
    dispatch_id: str,
    node_key: str = "root",
) -> dict[str, object]:
    return {
        "dispatch_id": dispatch_id,
        "task_id": ids.task_id,
        "flow_id": ids.flow_id,
        "assignment_id": ids.root_assignment_id,
        "flow_revision_id": ids.flow_revision_id,
        "flow_node_id": ids.root_node_id,
        "team_revision_id": team_revision_id(ids),
        "member_id": "root",
        "member_configuration_id": member_configuration_id(ids, "root"),
        "member_branch_basis_id": member_branch_basis_id(ids, "root"),
        "attempt_id": ids.root_attempt_id,
        "node_key": node_key,
        "flow_start_source_flow_id": None,
        "predecessor_dispatch_id": ids.current_dispatch_id,
        "status": "closed",
        "opened_reason": "child_return",
        "requested_provider": "codex",
        "resolved_provider": "codex",
        "provider_selection_basis": "default",
        "provider_route_kind": "codex",
        "model_override": None,
        "model_source": "provider_configuration",
        "effort_override": None,
        "effort_source": "provider_configuration",
        "gateway_profile": None,
        "gateway_profile_source": None,
        "provider_start_revision": 0,
        "provider_start_attempt_count": 0,
        "next_provider_start_at": None,
        "provider_start_retry_kind": None,
        "provider_start_last_error_code": None,
        "created_at": NOW,
        "adapter_started_at": NOW,
        "last_node_activity_at": NOW,
        "node_activity_revision": 0,
        "closed_at": NOW,
        "closed_reason": "boundary",
    }

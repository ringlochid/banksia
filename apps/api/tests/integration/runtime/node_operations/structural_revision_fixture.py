from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import autoclaw.runtime.node_operations.executor as executor_module
from autoclaw.persistence import RuntimeBase
from autoclaw.runtime.ids import flow_node_id, node_plan_revision_id
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.node_operations.follow_on import SupportProjectionPublisher
from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    RuntimeIds,
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)


class SyncSessionAdapter:
    """Run async domain methods through a real synchronous SQLite ORM session."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._session = factory()

    async def __aenter__(self) -> SyncSessionAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc, traceback
        if exc_type is not None:
            self._session.rollback()
        self._session.close()

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.get(*args, **kwargs)

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalar(*args, **kwargs)

    async def scalars(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalars(*args, **kwargs)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def flush(self, objects: tuple[object, ...] | None = None) -> None:
        self._session.flush(objects)

    def add(self, instance: object) -> None:
        self._session.add(instance)

    def add_all(self, instances: tuple[object, ...]) -> None:
        self._session.add_all(instances)

    def get_bind(self) -> Engine:
        return cast(Engine, self._session.get_bind())


type SessionFactory = Callable[[], SyncSessionAdapter]
type StructuralNodeFixture = tuple[
    str,
    str,
    str,
    dict[str, object] | None,
    dict[str, object] | None,
]


@dataclass(frozen=True)
class StructuralRevisionContext:
    executor: NodeOperationExecutor
    session_factory: SessionFactory
    engine: Engine
    ids: RuntimeIds

    @property
    def scope(self) -> NodeOperationScope:
        return NodeOperationScope(
            task_id=self.ids.task_id,
            dispatch_id=self.ids.current_dispatch_id,
        )


@asynccontextmanager
async def seeded_structural_revision_context(
    tmp_path: Path,
    *,
    suffix: str,
    support_projection_publisher: SupportProjectionPublisher | None = None,
) -> AsyncIterator[StructuralRevisionContext]:
    engine = create_runtime_schema_engine(tmp_path, name=f"structural-{suffix}.sqlite")
    with engine.begin() as connection:
        seed_catalog(connection)
        ids = seed_runtime_scope(connection, suffix=suffix)
        _seed_definition_content(connection)
        _seed_structural_graph(connection, ids)
    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def session_factory() -> SyncSessionAdapter:
        return SyncSessionAdapter(sync_factory)

    try:
        with patch.object(
            executor_module,
            "get_session_factory",
            return_value=session_factory,
        ):
            yield StructuralRevisionContext(
                executor=NodeOperationExecutor(
                    support_projection_publisher=support_projection_publisher,
                ),
                session_factory=session_factory,
                engine=engine,
                ids=ids,
            )
    finally:
        engine.dispose()


def _seed_definition_content(connection: Connection) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["role_revisions"]
        .update()
        .values(
            content_json={
                "id": "role.target",
                "description": "Target role.",
                "allowed_node_kinds": ["root", "parent", "worker"],
            }
        )
    )
    connection.execute(
        tables["policy_revisions"]
        .update()
        .values(
            content_json={
                "id": "policy.target",
                "description": "Target policy.",
                "applies_to": ["root", "parent", "worker"],
            }
        )
    )


def _seed_structural_graph(connection: Connection, ids: RuntimeIds) -> None:
    tables = RuntimeBase.metadata.tables
    connection.execute(
        tables["flow_nodes"]
        .update()
        .where(tables["flow_nodes"].c.flow_node_id == ids.root_node_id)
        .values(child_node_keys_json=["child", "branch", "outside_parent"])
    )
    rows: tuple[StructuralNodeFixture, ...] = (
        ("branch", "root", "parent", None, None),
        (
            "producer",
            "branch",
            "worker",
            None,
            {
                "artifacts": [
                    {
                        "slot": "source",
                        "description": "Primary source artifact.",
                    }
                ]
            },
        ),
        (
            "alternate",
            "branch",
            "worker",
            None,
            {
                "artifacts": [
                    {
                        "slot": "alternate",
                        "description": "Alternate source artifact.",
                    }
                ]
            },
        ),
        (
            "reviewer",
            "branch",
            "worker",
            {"artifacts": [{"slot": "source", "required": True}]},
            None,
        ),
        ("outside_parent", "root", "parent", None, None),
        ("outside_leaf", "outside_parent", "worker", None, None),
    )
    child_keys = {
        "branch": ["producer", "alternate", "reviewer"],
        "outside_parent": ["outside_leaf"],
    }
    for order_index, (node_key, parent_key, kind, consumes, produces) in enumerate(
        rows,
        start=2,
    ):
        _insert_structural_node(
            connection,
            ids=ids,
            order_index=order_index,
            node_key=node_key,
            parent_key=parent_key,
            kind=kind,
            child_keys=child_keys.get(node_key, []),
            consumes=consumes,
            produces=produces,
        )


def _insert_structural_node(
    connection: Connection,
    *,
    ids: RuntimeIds,
    order_index: int,
    node_key: str,
    parent_key: str,
    kind: str,
    child_keys: list[str],
    consumes: dict[str, object] | None,
    produces: dict[str, object] | None,
) -> None:
    tables = RuntimeBase.metadata.tables
    node_id = flow_node_id(ids.flow_revision_id, node_key)
    connection.execute(
        tables["flow_nodes"].insert(),
        {
            "flow_node_id": node_id,
            "flow_id": ids.flow_id,
            "flow_revision_id": ids.flow_revision_id,
            "node_key": node_key,
            "parent_node_key": parent_key,
            "node_kind": kind,
            "role_key": "role.target",
            "role_revision_no": 1,
            "role_description": "Target role.",
            "role_instruction": None,
            "policy_key": "policy.target",
            "policy_revision_no": 1,
            "policy_description": "Target policy.",
            "policy_instruction": None,
            "description": f"{node_key} node.",
            "node_instruction": None,
            "child_node_keys_json": child_keys,
            "consumes_json": consumes,
            "produces_json": produces,
            "criteria_json": [],
            "child_defaults_json": None,
            "state": "ready",
            "current_assignment_id": None,
            "order_index": order_index,
        },
    )
    connection.execute(
        tables["node_plan_revisions"].insert(),
        {
            "node_plan_revision_id": node_plan_revision_id(ids.flow_revision_id, node_key),
            "flow_id": ids.flow_id,
            "flow_revision_id": ids.flow_revision_id,
            "flow_node_id": node_id,
            "role_key": "role.target",
            "role_revision_no": 1,
            "role_description": "Target role.",
            "role_instruction": None,
            "policy_key": "policy.target",
            "policy_revision_no": 1,
            "policy_description": "Target policy.",
            "policy_instruction": None,
        },
    )


__all__ = [
    "SessionFactory",
    "StructuralRevisionContext",
    "SyncSessionAdapter",
    "seeded_structural_revision_context",
]

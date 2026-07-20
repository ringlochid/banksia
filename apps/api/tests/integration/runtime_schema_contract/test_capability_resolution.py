from __future__ import annotations

from pathlib import Path

import pytest
from autoclaw.persistence import RuntimeBase
from sqlalchemy.exc import IntegrityError
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import (
    seed_runtime_scope,
)
from tests.helpers.sqlite_runtime import (
    create_runtime_schema_engine,
)


@pytest.mark.parametrize(
    ("column_name", "invalid_value"),
    (
        ("provider_native_access", "implicit"),
        ("provider_native_access_source", "provider"),
        ("network_access", "inherit"),
        ("network_access_source", "adapter"),
        ("human_direction", "prompt"),
        ("human_approval", "prompt"),
        ("human_input", "prompt"),
        ("human_review", "prompt"),
        ("command_run", "prompt"),
    ),
)
def test_frozen_dispatch_capability_values_are_closed_enums(
    tmp_path: Path,
    column_name: str,
    invalid_value: str,
) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        capabilities = RuntimeBase.metadata.tables["dispatch_capability_sets"]
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    capabilities.update()
                    .where(capabilities.c.dispatch_id == ids.current_dispatch_id)
                    .values({column_name: invalid_value})
                )
    finally:
        engine.dispose()


def test_each_dispatch_has_at_most_one_frozen_capability_set(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    RuntimeBase.metadata.tables["dispatch_capability_sets"].insert(),
                    {
                        "dispatch_id": ids.current_dispatch_id,
                        "provider_native_access": "restricted",
                        "provider_native_access_source": "controller",
                        "network_access": "deny",
                        "network_access_source": "controller",
                        "human_direction": "deny",
                        "human_approval": "deny",
                        "human_input": "deny",
                        "human_review": "deny",
                        "command_run": "deny",
                    },
                )
    finally:
        engine.dispose()

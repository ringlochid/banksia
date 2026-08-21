from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from oh_my_subagents.persistence import RuntimeBase
from tests.helpers.catalog_seed import seed_catalog
from tests.helpers.lineage_seed import seed_runtime_scope
from tests.helpers.sqlite_runtime import create_runtime_schema_engine


def test_attempt_rejects_negative_watchdog_replacement_count(tmp_path: Path) -> None:
    engine = create_runtime_schema_engine(tmp_path)
    try:
        with engine.begin() as connection:
            seed_catalog(connection)
            ids = seed_runtime_scope(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                attempts = RuntimeBase.metadata.tables["attempts"]
                connection.execute(
                    attempts.update()
                    .where(attempts.c.attempt_id == ids.root_attempt_id)
                    .values(watchdog_replacement_count=-1)
                )
    finally:
        engine.dispose()

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

import autoclaw.interfaces.cli as cli
import pytest
from autoclaw.config import get_settings
from autoclaw.main import create_app
from autoclaw.persistence.session import dispose_test_db_engine, get_async_engine
from autoclaw.runtime.post_commit import RuntimeEffectRouter
from autoclaw.runtime.projection import SupportProjectionOwner
from sqlalchemy import inspect
from sqlalchemy.engine import make_url


def _write_stale_flows_schema(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE flows (task_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        connection.commit()


async def test_lifespan_fails_closed_on_stale_runtime_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    monkeypatch.setenv("AUTOCLAW_ENV", "development")

    try:
        await cli.cmd_init(
            argparse.Namespace(
                config=str(config_path),
                data_dir=str(data_dir),
                database_url=None,
                host="127.0.0.1",
                port=8123,
                log_level="INFO",
                force=True,
                skip_db_upgrade=False,
                json=False,
            )
        )

        with cli.command_env(config_path=config_path):
            get_settings.cache_clear()
            database_path = Path(make_url(get_settings().database_url).database or "")
        await dispose_test_db_engine()

        await asyncio.to_thread(_write_stale_flows_schema, database_path)

        with cli.command_env(config_path=config_path):
            get_settings.cache_clear()
            app = create_app()
            with pytest.raises(
                RuntimeError,
                match=r"flows missing column .*Run `autoclaw db reset`\.",
            ):
                async with app.router.lifespan_context(app):
                    pass
    finally:
        await dispose_test_db_engine()


async def test_lifespan_creates_schema_only_for_genuinely_empty_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    monkeypatch.setenv("AUTOCLAW_ENV", "test")

    try:
        await cli.cmd_init(
            argparse.Namespace(
                config=str(config_path),
                data_dir=str(data_dir),
                database_url=None,
                host="127.0.0.1",
                port=8123,
                log_level="INFO",
                force=True,
                skip_db_upgrade=True,
                json=False,
            )
        )

        with cli.command_env(config_path=config_path, env="test"):
            get_settings.cache_clear()
            app = create_app()
            async with app.router.lifespan_context(app):
                assert isinstance(app.state.runtime_effect_router, RuntimeEffectRouter)
                assert isinstance(app.state.support_projection_owner, SupportProjectionOwner)
                assert app.state.support_projection_owner.is_accepting
                assert app.state.runtime_effect_router.health.snapshot().is_healthy
                assert all(
                    result.discovered_count == 0
                    for result in app.state.runtime_startup_audit.values()
                )
                assert all(
                    count == 0 for count in app.state.support_projection_startup_audit.values()
                )
                engine = get_async_engine()
                async with engine.connect() as connection:
                    table_names = set(
                        await connection.run_sync(
                            lambda sync_connection: inspect(sync_connection).get_table_names()
                        )
                    )
            assert not app.state.support_projection_owner.is_accepting
    finally:
        await dispose_test_db_engine()

    assert {"tasks", "role_definitions", "workflow_definitions"}.issubset(table_names)

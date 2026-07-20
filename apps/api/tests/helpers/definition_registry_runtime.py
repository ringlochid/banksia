from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

import autoclaw.interfaces.cli as cli
from autoclaw.config import get_settings
from autoclaw.paths import default_database_url
from autoclaw.persistence.session import (
    RuntimeAsyncSession,
    dispose_test_db_engine,
    install_sqlite_transaction_control,
)
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

type AsyncSessionFactory = async_sessionmaker[AsyncSession]


def _build_isolated_session_factory(database_url: str) -> tuple[AsyncEngine, AsyncSessionFactory]:
    url = make_url(database_url)
    engine_kwargs: dict[str, object] = {
        "echo": False,
    }
    if url.get_backend_name() == "sqlite":
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if url.database in {None, "", ":memory:"}:
            engine_kwargs["poolclass"] = StaticPool
        else:
            engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_pre_ping"] = True
    engine = create_async_engine(database_url, **engine_kwargs)
    if url.get_backend_name() == "sqlite":
        install_sqlite_transaction_control(engine.sync_engine)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(
            dbapi_connection: SQLiteConnection,
            connection_record: object,
        ) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine, async_sessionmaker(
        bind=engine,
        class_=RuntimeAsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


def _build_init_args(config_path: Path, data_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
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


@asynccontextmanager
async def initialized_registry(tmp_path: Path) -> AsyncIterator[AsyncSessionFactory]:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"
    database_url = default_database_url(data_dir)
    engine: AsyncEngine | None = None

    try:
        get_settings.cache_clear()
        await dispose_test_db_engine()
        await cli.cmd_init(_build_init_args(config_path, data_dir))
        with cli.command_env(config_path=config_path, database_url=database_url):
            get_settings.cache_clear()
            engine, session_factory = _build_isolated_session_factory(database_url)
            try:
                yield session_factory
            finally:
                await engine.dispose()
    finally:
        get_settings.cache_clear()
        await dispose_test_db_engine()


__all__ = ["AsyncSessionFactory", "initialized_registry"]

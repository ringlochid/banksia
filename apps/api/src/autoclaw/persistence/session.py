from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from sqlite3 import Connection as SQLiteConnection
from typing import Any
from weakref import WeakSet

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from autoclaw.config import get_settings
from autoclaw.persistence.schema_contract import (
    DatabaseSchemaMismatchError,
    create_configured_schema,
    list_schema_table_names,
    raise_schema_mismatch,
    verify_schema_contract,
)
from autoclaw.platform.environment import Environment

_ENGINE_BY_LOOP: dict[int, AsyncEngine] = {}
_SESSION_FACTORY_BY_LOOP: dict[int, async_sessionmaker[AsyncSession]] = {}
_OPEN_SESSIONS_BY_LOOP: dict[int, WeakSet[RuntimeAsyncSession]] = {}
_TEST_SQLITE_CLOSE_SETTLE_SECONDS = 0.2


class RuntimeAsyncSession(AsyncSession):
    """Async session with loop-scoped disposal tracking and ordinary commits."""

    _owner_loop_id: int

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._owner_loop_id = _loop_id()
        _register_open_session(self)

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            _discard_open_session(self)


async def ensure_database_schema() -> None:
    """Create a genuinely empty database or exactly verify a nonempty one."""

    engine = get_async_engine()
    async with engine.connect() as connection:
        existing_tables = await connection.run_sync(_table_names)
    if existing_tables:
        await verify_database_schema()
        return
    await create_empty_database_schema()


async def create_empty_database_schema() -> None:
    """Create the current schema only when the configured database has no tables."""

    from autoclaw.persistence import RuntimeBase

    engine = get_async_engine()
    async with engine.begin() as connection:
        await connection.run_sync(_create_configured_schema)
        existing_tables = await connection.run_sync(_table_names)
        if existing_tables:
            raise_schema_mismatch(["database is not empty: " + ", ".join(sorted(existing_tables))])
        await connection.run_sync(RuntimeBase.metadata.create_all)
        await connection.run_sync(_verify_database_schema_contract)


async def verify_database_schema() -> None:
    """Verify the configured database without issuing schema DDL."""

    engine = get_async_engine()
    async with engine.connect() as connection:
        await connection.run_sync(_verify_database_schema_contract)


async def ping_database() -> None:
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def dispose_db_engine() -> None:
    should_settle_sqlite_close = get_settings().env == Environment.TEST
    await _dispose_db_engine(wait_for_sqlite_close_settle=should_settle_sqlite_close)


async def dispose_test_db_engine() -> None:
    await _dispose_db_engine(wait_for_sqlite_close_settle=True)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    loop_id = _loop_id()
    if loop_id not in _SESSION_FACTORY_BY_LOOP:
        _SESSION_FACTORY_BY_LOOP[loop_id] = async_sessionmaker(
            bind=get_async_engine(),
            class_=RuntimeAsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SESSION_FACTORY_BY_LOOP[loop_id]


def get_database_schema_name() -> str | None:
    """Return the configured PostgreSQL schema, or ``None`` for SQLite."""

    settings = get_settings()
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        return None
    return settings.postgres_schema


def get_async_engine() -> AsyncEngine:
    settings = get_settings()
    loop_id = _loop_id()
    if loop_id not in _ENGINE_BY_LOOP:
        url = make_url(settings.database_url)
        engine_kwargs: dict[str, object] = {"echo": settings.database_echo}
        if url.get_backend_name() == "sqlite":
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if url.database in {None, "", ":memory:"}:
                engine_kwargs["poolclass"] = StaticPool
            else:
                engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_pre_ping"] = True
            postgres_schema = settings.postgres_schema
            engine_kwargs["connect_args"] = {"server_settings": {"search_path": postgres_schema}}
            engine_kwargs["execution_options"] = {"schema_translate_map": {None: postgres_schema}}

        engine = create_async_engine(settings.database_url, **engine_kwargs)
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
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

        _ENGINE_BY_LOOP[loop_id] = engine
    return _ENGINE_BY_LOOP[loop_id]


def install_sqlite_transaction_control(engine: Engine) -> None:
    """Make SQLAlchemy own SQLite ``BEGIN`` so savepoints stay transactional."""

    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _disable_legacy_sqlite_begin(
        dbapi_connection: SQLiteConnection,
        connection_record: object,
    ) -> None:
        del connection_record
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_sqlite_transaction(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN")


def _loop_id() -> int:
    return id(asyncio.get_running_loop())


async def _dispose_db_engine(*, wait_for_sqlite_close_settle: bool) -> None:
    sessions_by_loop = tuple(tuple(sessions) for sessions in _OPEN_SESSIONS_BY_LOOP.values())
    _OPEN_SESSIONS_BY_LOOP.clear()
    for sessions in sessions_by_loop:
        for session in sessions:
            with suppress(Exception):
                await session.close()
    engines = tuple(_ENGINE_BY_LOOP.values())
    for engine in engines:
        await engine.dispose()
    _ENGINE_BY_LOOP.clear()
    _SESSION_FACTORY_BY_LOOP.clear()

    if wait_for_sqlite_close_settle and any(_is_sqlite_engine(engine) for engine in engines):
        await asyncio.sleep(_TEST_SQLITE_CLOSE_SETTLE_SECONDS)


def _is_sqlite_engine(engine: AsyncEngine) -> bool:
    return engine.dialect.name == "sqlite"


def _register_open_session(session: RuntimeAsyncSession) -> None:
    _OPEN_SESSIONS_BY_LOOP.setdefault(_session_loop_id(session), WeakSet()).add(session)


def _discard_open_session(session: RuntimeAsyncSession) -> None:
    sessions = _OPEN_SESSIONS_BY_LOOP.get(_session_loop_id(session))
    if sessions is None:
        return
    sessions.discard(session)
    if not sessions:
        _OPEN_SESSIONS_BY_LOOP.pop(_session_loop_id(session), None)


def _session_loop_id(session: RuntimeAsyncSession) -> int:
    return session._owner_loop_id


def _configured_schema(connection: Connection) -> str | None:
    if connection.dialect.name != "postgresql":
        return None
    return get_settings().postgres_schema


def _create_configured_schema(connection: Connection) -> None:
    create_configured_schema(connection, _configured_schema(connection))


def _table_names(connection: Connection) -> set[str]:
    return list_schema_table_names(connection, _configured_schema(connection))


def _verify_database_schema_contract(connection: Connection) -> None:
    verify_schema_contract(connection, _configured_schema(connection))


__all__ = [
    "DatabaseSchemaMismatchError",
    "RuntimeAsyncSession",
    "create_empty_database_schema",
    "dispose_db_engine",
    "dispose_test_db_engine",
    "ensure_database_schema",
    "get_async_engine",
    "get_database_schema_name",
    "get_db_session",
    "get_session_factory",
    "install_sqlite_transaction_control",
    "ping_database",
    "verify_database_schema",
]

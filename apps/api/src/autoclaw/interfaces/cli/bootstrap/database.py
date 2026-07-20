from __future__ import annotations

import asyncio
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from autoclaw.config import get_settings
from autoclaw.definitions.registry import seed_definition_registry
from autoclaw.interfaces.cli.bootstrap.task_root_cleanup import (
    delete_controller_task_roots,
)
from autoclaw.interfaces.cli.progress import CliProgress
from autoclaw.persistence.session import (
    create_empty_database_schema,
    dispose_db_engine,
    ensure_database_schema,
    get_async_engine,
    get_session_factory,
    ping_database,
)

SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


@dataclass(frozen=True)
class DatabaseResetResult:
    database_backend: str
    deleted_task_root_count: int


async def ensure_database_ready(
    *,
    progress: CliProgress | None = None,
) -> None:
    """Create a genuinely empty database or verify an exact current schema."""

    database_url = get_settings().database_url
    _prepare_sqlite_database_parent(database_url)
    try:
        if progress is not None:
            progress.step("database", "Checking database connection")
        await ping_database()
        if progress is not None:
            progress.step("database", "Creating or verifying the exact database schema")
        await ensure_database_schema()
        await _seed_packaged_definitions(progress=progress)
    finally:
        await dispose_db_engine()

    if progress is not None:
        progress.done("database", "Database ready")


async def reset_database(
    *,
    data_boundary: Path,
    progress: CliProgress | None = None,
) -> DatabaseResetResult:
    """Destructively replace the configured schema and controller-owned task roots."""

    database_url = get_settings().database_url
    backend = make_url(database_url).get_backend_name()
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError(f"db reset does not support database backend {backend!r}")

    database_path: Path | None = None
    postgres_schema: str | None = None

    try:
        if backend == "sqlite":
            database_path = _required_sqlite_database_path(database_url)
            _validate_sqlite_reset_files(database_path)
            task_root_paths = await asyncio.to_thread(
                _read_sqlite_controller_task_roots,
                database_path,
            )
        else:
            postgres_schema = get_settings().postgres_schema
            if progress is not None:
                progress.warn(
                    "database",
                    "PostgreSQL reset requires operator-assured exclusive ownership of "
                    f"schema {postgres_schema!r}",
                )
            task_root_paths = await _read_postgres_controller_task_roots(postgres_schema)
    finally:
        await dispose_db_engine()

    try:
        if progress is not None:
            progress.step("database", "Deleting controller-owned task roots")
        deleted_task_roots = await asyncio.to_thread(
            delete_controller_task_roots,
            task_root_paths,
            data_boundary=data_boundary,
        )

        if progress is not None:
            progress.step("database", "Replacing the configured database schema")
        if database_path is not None:
            await asyncio.to_thread(_replace_sqlite_database, database_path)
        elif postgres_schema is not None:
            await _replace_postgres_schema(postgres_schema)
        else:
            raise RuntimeError("validated database backend is missing its reset target")

        await create_empty_database_schema()
        await _seed_packaged_definitions(progress=progress)
    finally:
        await dispose_db_engine()

    if progress is not None:
        progress.done("database", "Database reset complete")
    return DatabaseResetResult(
        database_backend=backend,
        deleted_task_root_count=len(deleted_task_roots),
    )


def sqlite_database_path(database_url: str) -> Path | None:
    """Return the configured SQLite path without resolving its final symlink."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().absolute()


async def _seed_packaged_definitions(*, progress: CliProgress | None) -> None:
    if progress is not None:
        progress.step("seed", "Seeding packaged definitions")
    async with get_session_factory()() as session:
        await seed_definition_registry(session)
        await session.commit()


def _prepare_sqlite_database_parent(database_url: str) -> None:
    database_path = sqlite_database_path(database_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)


def _required_sqlite_database_path(database_url: str) -> Path:
    database_path = sqlite_database_path(database_url)
    if database_path is None:
        raise ValueError("db reset requires a file-backed sqlite URL")
    return database_path


def _validate_sqlite_reset_files(database_path: Path) -> None:
    _reject_symlinked_sqlite_database(database_path)
    for sidecar_path in _sqlite_database_files(database_path)[1:]:
        _reject_unsafe_sqlite_sidecar(sidecar_path)


def _reject_symlinked_sqlite_database(database_path: Path) -> None:
    try:
        path_mode = database_path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(path_mode):
        raise ValueError(f"refusing to reset a symlinked SQLite database path: {database_path}")
    if not stat.S_ISREG(path_mode):
        raise ValueError(f"SQLite database path is not a regular file: {database_path}")


def _reject_unsafe_sqlite_sidecar(sidecar_path: Path) -> None:
    try:
        path_mode = sidecar_path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISREG(path_mode) or stat.S_ISLNK(path_mode):
        return
    raise ValueError(f"refusing to remove unsafe SQLite database sidecar: {sidecar_path}")


def _replace_sqlite_database(database_path: Path) -> None:
    _validate_sqlite_reset_files(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    for removable_path in _sqlite_database_files(database_path):
        removable_path.unlink(missing_ok=True)


def _sqlite_database_files(database_path: Path) -> tuple[Path, ...]:
    return (
        database_path,
        *(Path(f"{database_path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES),
    )


def _read_sqlite_controller_task_roots(database_path: Path) -> tuple[str, ...]:
    if not database_path.exists():
        return ()
    try:
        with sqlite3.connect(database_path) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
            ).fetchone()
            if table_exists is None:
                return ()
            columns = {
                str(row[1]) for row in connection.execute('PRAGMA table_info("tasks")').fetchall()
            }
            if "task_root_path" not in columns:
                return ()
            rows = connection.execute(
                "SELECT task_root_path FROM tasks WHERE task_root_path IS NOT NULL"
            ).fetchall()
    except sqlite3.DatabaseError:
        return ()
    return tuple(str(row[0]) for row in rows)


async def _read_postgres_controller_task_roots(schema_name: str) -> tuple[str, ...]:
    engine = get_async_engine()
    async with engine.connect() as connection:
        has_task_root_column = await connection.run_sync(
            lambda sync_connection: _postgres_has_task_root_column(
                sync_connection,
                schema_name,
            )
        )
        if not has_task_root_column:
            return ()
        rows = await connection.execute(
            text(
                f'SELECT task_root_path FROM "{schema_name}".tasks WHERE task_root_path IS NOT NULL'
            )
        )
        return tuple(str(row[0]) for row in rows)


def _postgres_has_task_root_column(connection: Connection, schema_name: str) -> bool:
    inspector = inspect(connection)
    if "tasks" not in inspector.get_table_names(schema=schema_name):
        return False
    return any(
        column.get("name") == "task_root_path"
        for column in inspector.get_columns("tasks", schema=schema_name)
    )


async def _replace_postgres_schema(schema_name: str) -> None:
    engine = get_async_engine()
    async with engine.begin() as connection:
        await connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))
        await connection.execute(CreateSchema(schema_name))


__all__ = [
    "DatabaseResetResult",
    "ensure_database_ready",
    "reset_database",
    "sqlite_database_path",
]

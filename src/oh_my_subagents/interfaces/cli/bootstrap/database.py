from __future__ import annotations

import asyncio
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from oh_my_subagents.config import get_settings
from oh_my_subagents.interfaces.cli.bootstrap.task_root_cleanup import (
    delete_controller_task_roots,
)
from oh_my_subagents.interfaces.cli.progress import CliProgress
from oh_my_subagents.persistence.database_backup import (
    create_postgres_schema_backup,
    create_sqlite_backup,
)
from oh_my_subagents.persistence.forward_upgrade import (
    execute_database_upgrade,
    identify_pending_database_upgrade,
)
from oh_my_subagents.persistence.schema_contract import list_schema_table_names
from oh_my_subagents.persistence.session import (
    create_empty_database_schema,
    dispose_db_engine,
    ensure_database_schema,
    get_async_engine,
    get_database_schema_name,
    get_session_factory,
    ping_database,
)
from oh_my_subagents.platform.workspace_files import (
    ensure_private_directory,
    protect_private_path,
)
from oh_my_subagents.workflows.bootstrap import seed_starter_workflows

SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_TASK_ID_ALPHABET = frozenset("0123456789abcdefghjkmnpqrstvwxyz")


@dataclass(frozen=True)
class DatabaseResetResult:
    database_backend: str
    deleted_task_root_count: int
    backup_path: Path | None


@dataclass(frozen=True)
class DatabaseUpgradeResult:
    database_backend: str
    applied_upgrade: str | None
    backup_path: Path | None


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
        await _seed_starter_workflows(progress=progress)
    finally:
        await dispose_db_engine()
    _protect_sqlite_database(database_url)

    if progress is not None:
        progress.done("database", "Database ready")


async def upgrade_database(
    *,
    progress: CliProgress | None = None,
) -> DatabaseUpgradeResult:
    """Create, verify, or strictly upgrade the configured Oh My Subagents database."""

    database_url = get_settings().database_url
    data_directory = get_settings().data_dir
    backend = make_url(database_url).get_backend_name()
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError(f"db upgrade does not support database backend {backend!r}")
    _prepare_sqlite_database_parent(database_url)
    applied_upgrade: str | None = None
    backup_path: Path | None = None
    try:
        if progress is not None:
            progress.step("database", "Checking database connection and schema")
        await ping_database()
        schema_name = get_database_schema_name()
        engine = get_async_engine()
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: list_schema_table_names(
                    sync_connection,
                    schema_name,
                )
            )
            pending_upgrade = (
                await connection.run_sync(
                    lambda sync_connection: identify_pending_database_upgrade(
                        sync_connection,
                        schema_name,
                    )
                )
                if table_names
                else None
            )

        if not table_names:
            if progress is not None:
                progress.step("database", "Creating the current database schema")
            await create_empty_database_schema()
        elif pending_upgrade is not None:
            await dispose_db_engine()
            if progress is not None:
                progress.step("database", f"Backing up the {backend} database")
            backup_path = await _create_database_backup(
                database_url,
                backend=backend,
                postgres_schema=schema_name,
                data_directory=data_directory,
                operation=pending_upgrade,
            )
            if progress is not None:
                progress.step("database", f"Applying schema upgrade {pending_upgrade}")
            engine = get_async_engine()
            async with engine.begin() as connection:
                was_applied = await connection.run_sync(
                    lambda sync_connection: execute_database_upgrade(
                        sync_connection,
                        schema_name=schema_name,
                        expected_upgrade=pending_upgrade,
                    )
                )
            if was_applied:
                applied_upgrade = pending_upgrade

        await ensure_database_schema()
        await _seed_starter_workflows(progress=progress)
    finally:
        await dispose_db_engine()
    _protect_sqlite_database(database_url)
    return DatabaseUpgradeResult(
        database_backend=backend,
        applied_upgrade=applied_upgrade,
        backup_path=backup_path,
    )


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
    should_backup = False

    try:
        if backend == "sqlite":
            database_path = _required_sqlite_database_path(database_url)
            _validate_sqlite_reset_files(database_path)
            should_backup = database_path.exists()
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
            should_backup = await _postgres_schema_exists(postgres_schema)
    finally:
        await dispose_db_engine()

    backup_path: Path | None = None
    try:
        if should_backup:
            if progress is not None:
                progress.step("database", f"Backing up the {backend} database")
            backup_path = await _create_database_backup(
                database_url,
                backend=backend,
                postgres_schema=postgres_schema,
                data_directory=data_boundary,
                operation="reset",
            )
        if progress is not None:
            progress.step("database", "Deleting controller-owned task roots")
        deleted_task_roots = await asyncio.to_thread(
            delete_controller_task_roots,
            _reset_deletable_task_roots(task_root_paths),
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
        await _seed_starter_workflows(progress=progress)
    finally:
        await dispose_db_engine()
    _protect_sqlite_database(database_url)

    if progress is not None:
        progress.done("database", "Database reset complete")
    return DatabaseResetResult(
        database_backend=backend,
        deleted_task_root_count=len(deleted_task_roots),
        backup_path=backup_path,
    )


def sqlite_database_path(database_url: str) -> Path | None:
    """Return the configured SQLite path without resolving its final symlink."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).expanduser().absolute()


def _reset_deletable_task_roots(task_root_paths: tuple[str, ...]) -> tuple[str, ...]:
    """Preserve accepted workspace Task directories across a DB reset."""

    return tuple(
        path for path in task_root_paths if not _is_workspace_task_root(Path(path).expanduser())
    )


def _is_workspace_task_root(path: Path) -> bool:
    task_id = path.name
    return (
        path.parent.name == ".oms"
        and len(task_id) == 10
        and task_id.startswith("t_")
        and all(character in _TASK_ID_ALPHABET for character in task_id[2:])
    )


async def _seed_starter_workflows(*, progress: CliProgress | None) -> None:
    if progress is not None:
        progress.step("seed", "Seeding Starter Workflows")
    async with get_session_factory()() as session:
        await seed_starter_workflows(session)
        await session.commit()


def _prepare_sqlite_database_parent(database_url: str) -> None:
    database_path = sqlite_database_path(database_url)
    if database_path is not None:
        ensure_private_directory(database_path.parent)


def _protect_sqlite_database(database_url: str) -> None:
    database_path = sqlite_database_path(database_url)
    if database_path is not None and database_path.exists():
        protect_private_path(database_path, is_directory=False)


def _required_sqlite_database_path(database_url: str) -> Path:
    database_path = sqlite_database_path(database_url)
    if database_path is None:
        raise ValueError("db reset requires a file-backed sqlite URL")
    return database_path


async def _create_database_backup(
    database_url: str,
    *,
    backend: str,
    postgres_schema: str | None,
    data_directory: Path,
    operation: str,
) -> Path:
    if backend == "sqlite":
        database_path = _required_sqlite_database_path(database_url)
        _validate_sqlite_reset_files(database_path)
        return await asyncio.to_thread(
            create_sqlite_backup,
            database_path,
            operation=operation,
        )
    if backend == "postgresql" and postgres_schema is not None:
        return await asyncio.to_thread(
            create_postgres_schema_backup,
            database_url,
            schema_name=postgres_schema,
            backup_directory=data_directory / "database-backups",
            operation=operation,
        )
    raise RuntimeError("validated database backend is missing its backup target")


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
    ensure_private_directory(database_path.parent)
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
        with closing(sqlite3.connect(database_path)) as connection:
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


async def _postgres_schema_exists(schema_name: str) -> bool:
    engine = get_async_engine()
    async with engine.connect() as connection:
        return bool(
            await connection.scalar(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema_name"
                    ")"
                ),
                {"schema_name": schema_name},
            )
        )


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
    "DatabaseUpgradeResult",
    "ensure_database_ready",
    "reset_database",
    "sqlite_database_path",
    "upgrade_database",
]

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

from banksia.platform.workspace_files import (
    ensure_private_directory,
    protect_private_path,
)


class DatabaseBackupError(RuntimeError):
    """Raised when Banksia cannot create a required database backup."""


def create_sqlite_backup(database_path: Path, *, operation: str) -> Path:
    """Create and validate an owner-private online backup of one SQLite database."""

    backup_path = database_path.with_name(
        f"{database_path.name}.before-{operation}-{_backup_suffix()}.backup"
    )
    backup_path.touch(mode=0o600, exist_ok=False)
    try:
        with (
            sqlite3.connect(database_path) as source,
            sqlite3.connect(backup_path) as target,
        ):
            source.backup(target)
            integrity_result = target.execute("PRAGMA integrity_check").fetchone()
            if integrity_result != ("ok",):
                raise DatabaseBackupError(
                    f"SQLite backup integrity check failed: {integrity_result!r}"
                )
    except Exception as exc:
        backup_path.unlink(missing_ok=True)
        if isinstance(exc, DatabaseBackupError):
            raise
        raise DatabaseBackupError(
            f"SQLite backup failed before any database change: {exc}"
        ) from exc
    protect_private_path(backup_path, is_directory=False)
    return backup_path


def create_postgres_schema_backup(
    database_url: str,
    *,
    schema_name: str,
    backup_directory: Path,
    operation: str,
) -> Path:
    """Create a custom-format dump of one Banksia PostgreSQL schema."""

    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise DatabaseBackupError(
            "PostgreSQL backup requires pg_dump from the PostgreSQL client tools; "
            "no database changes were made"
        )

    database_url_value = make_url(database_url)
    database_name = database_url_value.database
    if not database_name:
        raise DatabaseBackupError("PostgreSQL backup requires a database name")

    ensure_private_directory(backup_directory)
    backup_path = backup_directory / f"postgresql.before-{operation}-{_backup_suffix()}.dump"
    backup_path.touch(mode=0o600, exist_ok=False)
    command = [
        pg_dump,
        "--format=custom",
        "--strict-names",
        f"--schema={schema_name}",
        f"--file={backup_path}",
        *_postgres_connection_arguments(database_url),
        database_name,
    ]
    try:
        dump_result = subprocess.run(
            command,
            env=_postgres_client_environment(database_url),
            capture_output=True,
            text=True,
            check=False,
        )
        if dump_result.returncode != 0:
            raise DatabaseBackupError(
                "PostgreSQL backup failed before any database change: "
                f"{_bounded_diagnostic(dump_result.stderr)}"
            )
        if backup_path.stat().st_size == 0:
            raise DatabaseBackupError("PostgreSQL backup produced an empty archive")
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    protect_private_path(backup_path, is_directory=False)
    return backup_path


def _postgres_connection_arguments(database_url: str) -> list[str]:
    database_url_value = make_url(database_url)
    arguments: list[str] = []
    if database_url_value.host:
        arguments.extend(("--host", database_url_value.host))
    if database_url_value.port:
        arguments.extend(("--port", str(database_url_value.port)))
    if database_url_value.username:
        arguments.extend(("--username", database_url_value.username))
    return arguments


def _postgres_client_environment(database_url: str) -> dict[str, str]:
    database_url_value = make_url(database_url)
    environment = os.environ.copy()
    if database_url_value.password:
        environment["PGPASSWORD"] = database_url_value.password
    query_environment_names = {
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "sslmode": "PGSSLMODE",
    }
    for query_name, environment_name in query_environment_names.items():
        query_value = database_url_value.query.get(query_name)
        if query_value is not None:
            environment[environment_name] = str(query_value)
    asyncpg_ssl_mode = database_url_value.query.get("ssl")
    if isinstance(asyncpg_ssl_mode, str) and asyncpg_ssl_mode in {
        "allow",
        "disable",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    }:
        environment.setdefault("PGSSLMODE", asyncpg_ssl_mode)
    return environment


def _bounded_diagnostic(message: str) -> str:
    normalized = " ".join(message.split())
    return normalized[:500] or "no diagnostic was returned"


def _backup_suffix() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


__all__ = [
    "DatabaseBackupError",
    "create_postgres_schema_backup",
    "create_sqlite_backup",
]

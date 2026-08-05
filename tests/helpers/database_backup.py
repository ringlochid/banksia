from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path


def read_sqlite_reset_catalog(
    database_path: Path,
) -> tuple[frozenset[str], int, tuple[str, ...]]:
    """Read the catalog facts required by reset's packaged CLI proof."""

    with sqlite3.connect(database_path) as connection:
        table_names = frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        )
        workflow_count = int(
            connection.execute("SELECT COUNT(*) FROM workflow_definitions").fetchone()[0]
        )
        starter_workflow_ids = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT workflow_key FROM workflow_revisions "
                "WHERE provenance = 'starter_seed' ORDER BY workflow_key"
            ).fetchall()
        )
    return table_names, workflow_count, starter_workflow_ids


def read_sqlite_backup_marker(backup_path: Path) -> str:
    """Read the marker used by reset's real SQLite backup proof."""

    with sqlite3.connect(backup_path) as connection:
        row = connection.execute("SELECT value FROM reset_backup_marker").fetchone()
    assert row is not None
    return str(row[0])


def render_postgres_backup_sql(backup_path: Path) -> str:
    """Render a real custom archive so tests can prove its preserved rows."""

    result = subprocess.run(
        ["pg_restore", "--file=-", str(backup_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


__all__ = [
    "read_sqlite_backup_marker",
    "read_sqlite_reset_catalog",
    "render_postgres_backup_sql",
]

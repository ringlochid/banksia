from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from banksia.interfaces.cli.bootstrap.database import reset_database
from banksia.interfaces.cli.support import command_env, temporary_env
from banksia.persistence.session import dispose_db_engine, get_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"


@dataclass(frozen=True)
class _PostgresResetReadback:
    dedicated_schema_table_names: frozenset[str]
    workflow_definition_count: int
    public_schema_table_names: frozenset[str]


def _run_packaged_cli(*args: str) -> subprocess.CompletedProcess[str]:
    result = _invoke_packaged_cli(*args)
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _invoke_packaged_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("BANKSIA_")}
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SOURCE_ROOT)
        if not existing_pythonpath
        else os.pathsep.join((str(SOURCE_ROOT), existing_pythonpath))
    )
    return subprocess.run(
        [sys.executable, "-m", "banksia", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_db_reset_recreates_seeded_sqlite_database_on_packaged_cli_path(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    legacy_files = {
        tmp_path / "config" / "autoclaw" / "config.toml": b"legacy config marker\n",
        tmp_path / "data" / "autoclaw" / "keep.txt": b"legacy data marker\n",
        tmp_path / "config" / "systemd" / "user" / "autoclaw.service": (b"legacy service marker\n"),
    }
    for path, payload in legacy_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    database_path.write_bytes(b"stale")

    _run_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
    )

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        workflow_count = connection.execute("SELECT COUNT(*) FROM workflow_definitions").fetchone()[
            0
        ]
        starter_workflow_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT workflow_key FROM workflow_revisions "
                "WHERE provenance = 'starter_seed' ORDER BY workflow_key"
            ).fetchall()
        )
    assert {
        "workflow_definitions",
        "workflow_drafts",
        "workflow_revisions",
        "workflow_undo_receipts",
        "members",
        "member_configurations",
        "member_branch_bases",
        "team_revisions",
        "team_revision_members",
        "tasks",
        "operator_conversations",
        "operator_conversation_entries",
    }.issubset(table_names)
    assert workflow_count == 7
    assert starter_workflow_ids == (
        "bounded-maintenance-batch",
        "cross-layer-feature",
        "debug-and-verify",
        "evidence-synthesis",
        "reproducible-study",
        "reviewed-code-change",
        "technical-decision",
    )
    assert {path: path.read_bytes() for path in legacy_files} == legacy_files


def test_db_reset_deletes_controller_task_root_but_preserves_external_workspace(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    task_root = data_dir / "tasks" / "task.alpha"
    external_workspace = tmp_path / "external-workspace"

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    task_root.mkdir(parents=True)
    external_workspace.mkdir()
    external_file = external_workspace / "keep.txt"
    external_file.write_text("user owned", encoding="utf-8")
    (task_root / "workspace").symlink_to(external_workspace, target_is_directory=True)
    (task_root / "_runtime").mkdir()
    _insert_task(database_path, task_root=task_root)
    _insert_workspace_binding(database_path, workspace_root=external_workspace)

    result = _run_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
        "--json",
    )

    assert json.loads(result.stdout)["deleted_task_root_count"] == 1
    assert not task_root.exists()
    assert external_file.read_text(encoding="utf-8") == "user owned"


def test_db_reset_preserves_accepted_workspace_task_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    task_root = tmp_path / "workspace" / ".banksia" / "t_01234567"
    retained_file = task_root / "notes" / "retain.md"

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    retained_file.parent.mkdir(parents=True)
    retained_file.write_text("accepted workspace data", encoding="utf-8")
    _insert_task(database_path, task_root=task_root)

    result = _run_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
        "--json",
    )

    assert json.loads(result.stdout)["deleted_task_root_count"] == 0
    assert retained_file.read_text(encoding="utf-8") == "accepted workspace data"


def test_db_reset_rejects_controller_task_root_outside_data_boundary_before_destruction(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    external_task_root = tmp_path / "external-task-root"

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    external_task_root.mkdir()
    _insert_task(database_path, task_root=external_task_root)

    result = _invoke_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
    )

    assert result.returncode != 0
    assert "escapes the configured Banksia data boundary" in (result.stderr + result.stdout)
    assert external_task_root.is_dir()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_db_reset_rejects_symlinked_controller_task_root_before_destruction(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    external_task_root = tmp_path / "external-task-root"
    linked_task_root = data_dir / "tasks" / "task-link"

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    external_task_root.mkdir()
    linked_task_root.parent.mkdir(parents=True)
    linked_task_root.symlink_to(external_task_root, target_is_directory=True)
    _insert_task(database_path, task_root=linked_task_root)

    result = _invoke_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
    )

    assert result.returncode != 0
    assert "symlinked controller task root" in (result.stderr + result.stdout)
    assert linked_task_root.is_symlink()
    assert external_task_root.is_dir()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_db_reset_rejects_symlinked_task_root_ancestor_before_destruction(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    real_task_parent = data_dir / "real-tasks"
    real_task_root = real_task_parent / "task.alpha"
    linked_task_parent = data_dir / "tasks"

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    real_task_root.mkdir(parents=True)
    linked_task_parent.symlink_to(real_task_parent, target_is_directory=True)
    _insert_task(database_path, task_root=linked_task_parent / "task.alpha")

    result = _invoke_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
    )

    assert result.returncode != 0
    assert "symlinked controller task-root ancestor" in (result.stderr + result.stdout)
    assert linked_task_parent.is_symlink()
    assert real_task_root.is_dir()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_db_reset_rejects_unsafe_sidecar_before_deleting_task_roots(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    database_path = data_dir / "banksia.persistence"
    task_root = data_dir / "tasks" / "task.alpha"
    unsafe_sidecar = Path(f"{database_path}-journal")

    _run_packaged_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--log-level",
        "INFO",
        "--force",
    )
    task_root.mkdir(parents=True)
    _insert_task(database_path, task_root=task_root)
    unsafe_sidecar.mkdir()

    result = _invoke_packaged_cli(
        "db",
        "reset",
        "--config",
        str(config_path),
    )

    assert result.returncode != 0
    assert "unsafe SQLite database sidecar" in (result.stderr + result.stdout)
    assert task_root.is_dir()
    assert unsafe_sidecar.is_dir()
    unsafe_sidecar.rmdir()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_postgres_reset_recreates_only_dedicated_schema_and_seeds(
    tmp_path: Path,
) -> None:
    database_url = _require_disposable_postgres_url()
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"
    task_root = data_dir / "tasks" / "task.postgres"

    try:
        with (
            temporary_env({"BANKSIA_POSTGRES_SCHEMA": "banksia"}),
            command_env(
                config_path=config_path,
                data_dir=data_dir,
                database_url=database_url,
                env="test",
            ),
        ):
            await _create_postgres_reset_sentinel()
            await reset_database(data_boundary=data_dir)
            task_root.mkdir(parents=True)
            await _insert_postgres_reset_task(task_root)

            result = await reset_database(data_boundary=data_dir)
            readback = await _read_postgres_reset_state()
            await _drop_postgres_reset_sentinel()
    finally:
        await dispose_db_engine()

    assert result.database_backend == "postgresql"
    assert result.deleted_task_root_count == 1
    assert not task_root.exists()
    assert {"tasks", "workflow_definitions", "members", "team_revisions"}.issubset(
        readback.dedicated_schema_table_names
    )
    assert readback.workflow_definition_count == 7
    assert "banksia_reset_sentinel" in readback.public_schema_table_names


def _require_disposable_postgres_url() -> str:
    database_url = os.environ.get("BANKSIA_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BANKSIA_TEST_POSTGRES_URL not set")
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.casefold():
        pytest.skip("PostgreSQL reset proof requires an explicitly disposable test database")
    return database_url


async def _create_postgres_reset_sentinel() -> None:
    engine = get_async_engine()
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.banksia_reset_sentinel (id INTEGER)"
        )
    await dispose_db_engine()


async def _insert_postgres_reset_task(task_root: Path) -> None:
    engine = get_async_engine()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO banksia.tasks (
                    task_id,
                    workflow_key,
                    workflow_revision_no,
                    workflow_content_hash,
                    task_root_path,
                    created_at,
                    updated_at
                ) VALUES (
                    'task.postgres',
                    'cross-layer-feature',
                    1,
                    (
                        SELECT content_hash
                        FROM banksia.workflow_revisions
                        WHERE workflow_key = 'cross-layer-feature' AND revision_no = 1
                    ),
                    :task_root_path,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"task_root_path": str(task_root)},
        )
    await dispose_db_engine()


async def _read_postgres_reset_state() -> _PostgresResetReadback:
    engine = get_async_engine()
    async with engine.connect() as connection:
        dedicated_schema_table_names = frozenset(
            await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names(schema="banksia")
            )
        )
        workflow_definition_count = int(
            (
                await connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM banksia.workflow_definitions"
                )
            ).scalar_one()
        )
        public_schema_table_names = frozenset(
            await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names(schema="public")
            )
        )
    return _PostgresResetReadback(
        dedicated_schema_table_names=dedicated_schema_table_names,
        workflow_definition_count=workflow_definition_count,
        public_schema_table_names=public_schema_table_names,
    )


async def _drop_postgres_reset_sentinel() -> None:
    engine = get_async_engine()
    async with engine.begin() as connection:
        await connection.exec_driver_sql("DROP TABLE IF EXISTS public.banksia_reset_sentinel")


def _insert_task(database_path: Path, *, task_root: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        workflow_content_hash = connection.execute(
            "SELECT content_hash FROM workflow_revisions "
            "WHERE workflow_key = ? AND revision_no = ?",
            ("cross-layer-feature", 1),
        ).fetchone()
        assert workflow_content_hash is not None
        provided_values: dict[str, object] = {
            "task_id": "task.alpha",
            "workflow_key": "cross-layer-feature",
            "workflow_revision_no": 1,
            "workflow_content_hash": workflow_content_hash[0],
            "task_root_path": str(task_root),
            "created_at": "2026-07-18T00:00:00+00:00",
            "updated_at": "2026-07-18T00:00:00+00:00",
        }
        table_info = connection.execute('PRAGMA table_info("tasks")').fetchall()
        insert_columns = [str(row[1]) for row in table_info if str(row[1]) in provided_values]
        missing_required = [
            str(row[1])
            for row in table_info
            if (bool(row[3]) or bool(row[5]))
            and row[4] is None
            and str(row[1]) not in provided_values
        ]
        assert not missing_required, f"test task fixture lacks required columns: {missing_required}"
        quoted_columns = ", ".join(f'"{column}"' for column in insert_columns)
        placeholders = ", ".join("?" for _ in insert_columns)
        connection.execute(
            f'INSERT INTO "tasks" ({quoted_columns}) VALUES ({placeholders})',
            tuple(provided_values[column] for column in insert_columns),
        )
        connection.commit()


def _insert_workspace_binding(database_path: Path, *, workspace_root: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO workspace_bindings (
                task_id,
                normalized_root_path,
                bound_at
            ) VALUES (?, ?, ?)
            """,
            (
                "task.alpha",
                str(workspace_root),
                "2026-07-18T00:00:00+00:00",
            ),
        )
        connection.commit()

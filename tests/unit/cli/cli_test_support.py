from __future__ import annotations

import argparse
import socket
import sqlite3
from pathlib import Path

from oh_my_subagents.config import DEFAULT_API_PORT, DEFAULT_LOG_LEVEL
from oh_my_subagents.interfaces.cli.bootstrap.config import (
    build_initial_config_sections,
    config_sections_to_text,
)
from oh_my_subagents.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)
from oh_my_subagents.workflows.bootstrap import STARTER_WORKFLOW_FILENAMES

SEED_KIND_TO_TABLE = {"workflows": "workflow_definitions"}
SEEDED_REGISTRY_TABLES = {
    "workflow_definitions",
    "workflow_revisions",
    "workflow_drafts",
    "workflow_undo_receipts",
    "tasks",
}


def build_cli_init_args(config_path: Path, data_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=str(config_path),
        data_dir=str(data_dir),
        database_url=None,
        host="127.0.0.1",
        port=DEFAULT_API_PORT,
        log_level=DEFAULT_LOG_LEVEL,
        force=True,
        skip_db_upgrade=False,
        json=True,
    )


def write_local_cli_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        config_sections_to_text(
            build_initial_config_sections(
                data_dir=data_dir,
                database_url=f"sqlite+aiosqlite:///{data_dir / 'banksia.persistence'}",
                host="127.0.0.1",
                port=18125,
                log_level="WARNING",
            )
        ),
        encoding="utf-8",
    )
    return config_path


def build_provider_check_snapshot(
    provider: ProviderKind,
    *,
    outcome: ProviderCheckOutcome,
    is_ready: bool,
    detail: str,
    authentication: ProviderCheckAxisStatus = ProviderCheckAxisStatus.NOT_CHECKED,
    authentication_method: ProviderAuthenticationMethod | None = None,
) -> ProviderCheckSnapshot:
    if is_ready and authentication_method is None:
        authentication_method = ProviderAuthenticationMethod.SUBSCRIPTION
    return ProviderCheckSnapshot(
        kind=provider,
        outcome=outcome,
        is_ready=is_ready,
        service_identity="tester",
        native_home=f"/tmp/{provider.value}-home",
        authentication=authentication,
        authentication_method=authentication_method,
        reachability=ProviderCheckAxisStatus.NOT_CHECKED,
        detail=detail,
    )


def find_available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return int(probe_socket.getsockname()[1])


def count_packaged_seed_definitions() -> dict[str, int]:
    return {"workflows": len(STARTER_WORKFLOW_FILENAMES)}


def read_seeded_registry_counts(database_path: Path) -> tuple[set[str], dict[str, int]]:
    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        counts = {
            kind: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for kind, table in SEED_KIND_TO_TABLE.items()
        }
    return table_names, counts


def assert_seeded_registry_is_bootstrapped(database_path: Path) -> None:
    table_names, seeded_counts = read_seeded_registry_counts(database_path)
    assert SEEDED_REGISTRY_TABLES.issubset(table_names)
    assert seeded_counts == count_packaged_seed_definitions()


def write_systemctl_show_script(
    script_path: Path,
    log_path: Path,
    *,
    active_state: str,
    sub_state: str,
) -> None:
    show_output = "\n".join(
        [
            "LoadState=loaded",
            "UnitFileState=enabled",
            f"ActiveState={active_state}",
            f"SubState={sub_state}",
            "FragmentPath=/tmp/banksia.service",
        ]
    )
    script_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from pathlib import Path",
                "import sys",
                f"log_path = Path({str(log_path)!r})",
                "with log_path.open('a', encoding='utf-8') as handle:",
                "    handle.write(' '.join(sys.argv[1:]) + '\\n')",
                "args = sys.argv[1:]",
                "if args and args[0] == '--user':",
                "    args = args[1:]",
                "if args and args[0] == 'show':",
                f"    sys.stdout.write({show_output!r} + '\\n')",
                "sys.exit(0)",
            ]
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)

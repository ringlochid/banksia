from __future__ import annotations

import argparse
import socket
import sqlite3
from pathlib import Path

from autoclaw.config import DEFAULT_API_PORT, DEFAULT_LOG_LEVEL
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.definitions.seeds import resolve_packaged_seed_definitions_root
from autoclaw.interfaces.cli.bootstrap.config import settings_to_config_text
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
)
from autoclaw.runtime.providers import (
    ProviderAuthenticationMethod,
    ProviderCheckAxisStatus,
)

SEED_KIND_TO_TABLE = {
    "roles": "role_definitions",
    "policies": "policy_definitions",
    "workflows": "workflow_definitions",
}
SEEDED_REGISTRY_TABLES = {
    "role_definitions",
    "role_revisions",
    "policy_definitions",
    "policy_revisions",
    "workflow_definitions",
    "workflow_revisions",
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
        settings_to_config_text(
            data_dir=data_dir,
            database_url=f"sqlite+aiosqlite:///{data_dir / 'autoclaw.persistence'}",
            host="127.0.0.1",
            port=18125,
            log_level="WARNING",
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
        authentication_method = (
            ProviderAuthenticationMethod.TOKEN
            if provider is ProviderKind.OPENCLAW
            else ProviderAuthenticationMethod.SUBSCRIPTION
        )
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
    with resolve_packaged_seed_definitions_root() as definitions_root:
        return {
            kind: len(list(definitions_root.joinpath(kind).glob("*.yaml")))
            for kind in SEED_KIND_TO_TABLE
        }


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
            "FragmentPath=/tmp/autoclaw.service",
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

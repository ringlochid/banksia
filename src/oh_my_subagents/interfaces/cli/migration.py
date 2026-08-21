from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

from oh_my_subagents.interfaces.cli.bootstrap.config import (
    ConfigSections,
    config_sections_to_text,
    read_config_sections,
    write_config_text_atomically,
)
from oh_my_subagents.interfaces.cli.support import print_json
from oh_my_subagents.paths import (
    default_config_path,
    default_data_dir,
    legacy_default_config_path,
    legacy_default_data_dir,
    platform_dirs_for,
)
from oh_my_subagents.platform.managed_services import (
    ManagedServiceExecutionState,
    ManagedServiceInstallationState,
    ManagedServiceManager,
    ManagedServiceTarget,
    default_service_log_path,
    get_managed_service_manager,
)
from oh_my_subagents.platform.workspace_files import ensure_private_directory
from oh_my_subagents.product_identity import (
    LEGACY_BANKSIA_IDENTITY,
    OMS_IDENTITY,
    ProductIdentity,
)


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source_config_path: Path
    target_config_path: Path
    source_data_dir: Path | None
    target_data_dir: Path | None
    copied_files: tuple[Path, ...]
    reused_files: tuple[Path, ...]
    service_migrated: bool
    service_started: bool


def cmd_migrate_from_banksia(args: argparse.Namespace) -> int:
    result = migrate_from_banksia(
        source_config_path=args.source_config,
        target_config_path=args.config,
        should_migrate_service=not args.no_service,
    )
    payload = {
        "ok": True,
        "source_config_path": str(result.source_config_path),
        "target_config_path": str(result.target_config_path),
        "source_data_dir": (
            str(result.source_data_dir) if result.source_data_dir is not None else None
        ),
        "target_data_dir": (
            str(result.target_data_dir) if result.target_data_dir is not None else None
        ),
        "copied_files": [str(path) for path in result.copied_files],
        "reused_files": [str(path) for path in result.reused_files],
        "service_migrated": result.service_migrated,
        "service_started": result.service_started,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Migrated Banksia state to {result.target_config_path}")
        if result.service_migrated:
            state = "started" if result.service_started else "installed"
            print(f"Replaced the Banksia background service; OMS is {state}")
    return 0


def migrate_from_banksia(
    *,
    source_config_path: Path | None = None,
    target_config_path: Path | None = None,
    source_default_data_dir: Path | None = None,
    target_default_data_dir: Path | None = None,
    should_migrate_service: bool = True,
    legacy_service_manager: ManagedServiceManager | None = None,
    canonical_service_manager: ManagedServiceManager | None = None,
) -> MigrationResult:
    """Copy default Banksia state and replace its installed native service explicitly."""

    source_config = (source_config_path or legacy_default_config_path()).expanduser().resolve()
    target_config = (target_config_path or default_config_path()).expanduser().resolve()
    source_default_data = (
        (source_default_data_dir or legacy_default_data_dir()).expanduser().resolve()
    )
    target_default_data = (target_default_data_dir or default_data_dir()).expanduser().resolve()
    if not source_config.is_file():
        raise FileNotFoundError(f"Banksia config was not found: {source_config}")
    if source_config == target_config:
        raise ValueError("source and target config paths must be different")

    source_sections = read_config_sections(source_config)
    candidate_sections, source_data, target_data = _migration_config_candidate(
        source_sections,
        source_default_data_dir=source_default_data,
        target_default_data_dir=target_default_data,
    )
    rendered_config = config_sections_to_text(candidate_sections)

    legacy_manager = legacy_service_manager
    canonical_manager = canonical_service_manager
    source_target = _service_target(source_config, LEGACY_BANKSIA_IDENTITY)
    target_target = _service_target(target_config, OMS_IDENTITY)
    legacy_was_installed = False
    legacy_was_active = False
    if should_migrate_service:
        legacy_manager = legacy_manager or get_managed_service_manager(
            identity=LEGACY_BANKSIA_IDENTITY
        )
        canonical_manager = canonical_manager or get_managed_service_manager(identity=OMS_IDENTITY)
        legacy_inspection = legacy_manager.inspect(source_target)
        canonical_inspection = canonical_manager.inspect(target_target)
        legacy_was_installed = (
            legacy_inspection.installation_state is ManagedServiceInstallationState.INSTALLED
        )
        legacy_was_active = legacy_inspection.execution_state in {
            ManagedServiceExecutionState.RUNNING,
            ManagedServiceExecutionState.STARTING,
        }
        if legacy_was_installed and canonical_inspection.is_installed:
            raise RuntimeError(
                "both Banksia and Oh My Subagents native services are installed; "
                "remove one before migration"
            )
        if legacy_was_installed:
            legacy_manager.uninstall(source_target)

    copied: list[Path] = []
    reused: list[Path] = []
    try:
        if source_data is not None and target_data is not None:
            _copy_default_data_tree(
                source_data,
                target_data,
                copied=copied,
                reused=reused,
            )
        _write_or_verify_text(
            target_config,
            rendered_config,
            copied=copied,
            reused=reused,
        )
        _copy_provider_environment(
            source_config,
            target_config,
            copied=copied,
            reused=reused,
        )
        if should_migrate_service and legacy_was_installed:
            assert canonical_manager is not None
            canonical_manager.install(target_target, should_start=legacy_was_active)
    except BaseException:
        if should_migrate_service and legacy_was_installed:
            assert legacy_manager is not None
            legacy_manager.install(source_target, should_start=legacy_was_active)
        raise

    return MigrationResult(
        source_config_path=source_config,
        target_config_path=target_config,
        source_data_dir=source_data,
        target_data_dir=target_data,
        copied_files=tuple(copied),
        reused_files=tuple(reused),
        service_migrated=legacy_was_installed,
        service_started=legacy_was_installed and legacy_was_active,
    )


def _migration_config_candidate(
    source: ConfigSections,
    *,
    source_default_data_dir: Path,
    target_default_data_dir: Path,
) -> tuple[ConfigSections, Path | None, Path | None]:
    candidate = {section: dict(values) for section, values in source.items()}
    paths = candidate.setdefault("paths", {})
    configured_data = Path(paths.get("data_dir", source_default_data_dir)).expanduser().resolve()
    uses_default_data = configured_data == source_default_data_dir
    if uses_default_data:
        paths["data_dir"] = target_default_data_dir
    database = candidate.setdefault("database", {})
    raw_url = database.get("url")
    if raw_url is None:
        if uses_default_data:
            database["url"] = _sqlite_url(target_default_data_dir / OMS_IDENTITY.database_filename)
    else:
        parsed = make_url(str(raw_url))
        if (
            uses_default_data
            and parsed.get_backend_name() == "sqlite"
            and parsed.database is not None
        ):
            source_database = Path(parsed.database).expanduser().resolve()
            if source_database.is_relative_to(source_default_data_dir):
                relative = source_database.relative_to(source_default_data_dir)
                if relative == Path(LEGACY_BANKSIA_IDENTITY.database_filename):
                    relative = Path(OMS_IDENTITY.database_filename)
                database["url"] = _sqlite_url(target_default_data_dir / relative)
        elif parsed.get_backend_name() == "postgresql" and "postgres_schema" not in database:
            database["postgres_schema"] = LEGACY_BANKSIA_IDENTITY.postgres_schema
    if not uses_default_data:
        return candidate, None, None
    return candidate, source_default_data_dir, target_default_data_dir


def _copy_default_data_tree(
    source: Path,
    target: Path,
    *,
    copied: list[Path],
    reused: list[Path],
) -> None:
    if not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError(f"Banksia data directory is not a real directory: {source}")
    ensure_private_directory(target)
    for entry in sorted(source.rglob("*")):
        if entry.is_symlink():
            raise RuntimeError(f"Banksia data contains a symbolic link: {entry}")
        relative = entry.relative_to(source)
        if relative == Path(LEGACY_BANKSIA_IDENTITY.database_filename):
            relative = Path(OMS_IDENTITY.database_filename)
        destination = target / relative
        if entry.is_dir():
            ensure_private_directory(destination)
            continue
        if not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
            raise RuntimeError(f"Banksia data contains an unsupported file type: {entry}")
        if entry.name.endswith(("-wal", "-shm", "-journal")):
            continue
        _copy_or_verify_file(entry, destination, copied=copied, reused=reused)


def _copy_provider_environment(
    source_config: Path,
    target_config: Path,
    *,
    copied: list[Path],
    reused: list[Path],
) -> None:
    source = source_config.parent / LEGACY_BANKSIA_IDENTITY.provider_environment_filename
    if not source.exists():
        return
    target = target_config.parent / OMS_IDENTITY.provider_environment_filename
    _copy_or_verify_file(source, target, copied=copied, reused=reused)


def _copy_or_verify_file(
    source: Path,
    target: Path,
    *,
    copied: list[Path],
    reused: list[Path],
) -> None:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"migration source is not a real regular file: {source}")
    if target.exists():
        if (
            target.is_symlink()
            or not target.is_file()
            or not filecmp.cmp(source, target, shallow=False)
        ):
            raise FileExistsError(f"refusing to overwrite different OMS state: {target}")
        reused.append(target)
        return
    ensure_private_directory(target.parent)
    temporary = target.with_name(f".{target.name}.migration-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary, follow_symlinks=False)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    copied.append(target)


def _write_or_verify_text(
    target: Path,
    text: str,
    *,
    copied: list[Path],
    reused: list[Path],
) -> None:
    if target.exists():
        if (
            target.is_symlink()
            or not target.is_file()
            or target.read_text(encoding="utf-8") != text
        ):
            raise FileExistsError(f"refusing to overwrite different OMS config: {target}")
        reused.append(target)
        return
    ensure_private_directory(target.parent)
    write_config_text_atomically(target, text)
    copied.append(target)


def _service_target(config_path: Path, identity: ProductIdentity) -> ManagedServiceTarget:
    if identity is OMS_IDENTITY:
        log_path = default_service_log_path()
    else:
        log_path = Path(platform_dirs_for(LEGACY_BANKSIA_IDENTITY).user_log_path) / "controller.log"
    return ManagedServiceTarget(
        config_path=config_path,
        python_executable=Path(sys.executable).resolve(),
        log_path=log_path,
    )


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


__all__ = ["MigrationResult", "cmd_migrate_from_banksia", "migrate_from_banksia"]

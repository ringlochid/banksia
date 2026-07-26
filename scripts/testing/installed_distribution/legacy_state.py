from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LegacyStateOracle:
    roots: tuple[Path, ...]
    service_path: Path
    files: dict[Path, tuple[int, bytes]]


def create_legacy_state_oracle(
    *,
    config_home: Path,
    data_home: Path,
    cache_home: Path,
) -> LegacyStateOracle:
    roots = (
        config_home / "autoclaw",
        data_home / "autoclaw",
        cache_home / "autoclaw",
    )
    service_path = config_home / "systemd" / "user" / "autoclaw.service"
    fixture_files = {
        roots[0] / "config.toml": b"legacy config marker\n",
        roots[1] / "tasks" / "keep.txt": b"legacy data marker\n",
        roots[2] / "keep.cache": b"legacy cache marker\n",
        service_path: b"[Unit]\nDescription=legacy service marker\n",
    }
    for path, payload in fixture_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return LegacyStateOracle(
        roots=roots,
        service_path=service_path,
        files=snapshot_legacy_state(roots=roots, service_path=service_path),
    )


def assert_legacy_state_unchanged(oracle: LegacyStateOracle) -> None:
    actual = snapshot_legacy_state(roots=oracle.roots, service_path=oracle.service_path)
    if actual != oracle.files:
        raise AssertionError("Banksia accessed or changed neighboring legacy product state")


def snapshot_legacy_state(
    *,
    roots: tuple[Path, ...],
    service_path: Path,
) -> dict[Path, tuple[int, bytes]]:
    paths = [path for root in roots for path in sorted(root.rglob("*")) if path.is_file()]
    paths.append(service_path)
    return {path: (path.stat().st_mode & 0o777, path.read_bytes()) for path in paths}

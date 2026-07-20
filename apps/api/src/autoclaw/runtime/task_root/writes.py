from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel


def encode_projection_json(payload: BaseModel) -> bytes:
    """Encode one typed support projection deterministically."""

    materialized = payload.model_dump(mode="json")
    return (json.dumps(materialized, indent=2, sort_keys=True) + "\n").encode()


def replace_projection_files(files: Mapping[Path, bytes]) -> None:
    """Stage and atomically replace one same-directory support projection set."""

    if not files:
        raise ValueError("projection replacement requires at least one file")
    parents = {path.parent for path in files}
    if len(parents) != 1:
        raise ValueError("projection replacement files must share one destination directory")

    destination_dir = parents.pop()
    destination_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".autoclaw-projection-", dir=destination_dir))
    try:
        staged_files: list[tuple[Path, Path]] = []
        for destination, content in files.items():
            staged_path = staging_dir / destination.name
            with staged_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            staged_files.append((staged_path, destination))
        _sync_directory(staging_dir)

        for staged_path, destination in staged_files:
            os.replace(staged_path, destination)
        _sync_directory(destination_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["encode_projection_json", "replace_projection_files"]

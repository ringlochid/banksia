from __future__ import annotations

from contextlib import AbstractContextManager
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

_PACKAGED_SEED_DEFINITIONS_ROOT = resources.files(__name__)


def get_packaged_seed_definitions_root() -> Traversable:
    return _PACKAGED_SEED_DEFINITIONS_ROOT


def resolve_packaged_seed_definitions_root() -> AbstractContextManager[Path]:
    return resources.as_file(_PACKAGED_SEED_DEFINITIONS_ROOT)


__all__ = [
    "get_packaged_seed_definitions_root",
    "resolve_packaged_seed_definitions_root",
]

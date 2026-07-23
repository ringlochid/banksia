from __future__ import annotations

from enum import StrEnum


class NodeKind(StrEnum):
    """Residual runtime shape derived from Team membership, never authored authority."""

    ROOT = "root"
    PARENT = "parent"
    WORKER = "worker"


__all__ = ["NodeKind"]

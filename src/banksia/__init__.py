from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("banksia")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

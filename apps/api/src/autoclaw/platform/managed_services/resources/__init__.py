from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable

_MANAGED_SERVICE_RESOURCES_ROOT = resources.files(__name__)


def get_managed_service_resources_root() -> Traversable:
    return _MANAGED_SERVICE_RESOURCES_ROOT


def get_systemd_service_template() -> Traversable:
    return _MANAGED_SERVICE_RESOURCES_ROOT.joinpath("systemd", "autoclaw.service")


__all__ = [
    "get_managed_service_resources_root",
    "get_systemd_service_template",
]

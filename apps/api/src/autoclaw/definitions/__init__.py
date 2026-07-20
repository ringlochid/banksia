from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from autoclaw.definitions import compiler, contracts, registry, seeds

_LAZY_SUBMODULE_EXPORTS: dict[str, str] = {
    "compiler": "autoclaw.definitions.compiler",
    "contracts": "autoclaw.definitions.contracts",
    "registry": "autoclaw.definitions.registry",
    "seeds": "autoclaw.definitions.seeds",
}


def __getattr__(name: str) -> Any:
    submodule_name = _LAZY_SUBMODULE_EXPORTS.get(name)
    if submodule_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = import_module(submodule_name)
    globals()[name] = value
    return value


__all__ = ["compiler", "contracts", "registry", "seeds"]

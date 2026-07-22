from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from banksia.definitions.registry.current import (
        RegistryWorkflowDefinition,
        build_role_policy_lookup,
        compile_current_workflow,
        compile_current_workflow_launch_snapshot,
        load_current_policy,
        load_current_role,
        load_current_workflow,
        load_policy_revision,
        load_role_revision,
    )
    from banksia.definitions.registry.seeds import seed_definition_registry
    from banksia.definitions.registry.upsert import (
        upsert_policy_definition,
        upsert_role_definition,
        upsert_workflow_definition,
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "RegistryWorkflowDefinition": (
        "banksia.definitions.registry.current",
        "RegistryWorkflowDefinition",
    ),
    "build_role_policy_lookup": (
        "banksia.definitions.registry.current",
        "build_role_policy_lookup",
    ),
    "compile_current_workflow": (
        "banksia.definitions.registry.current",
        "compile_current_workflow",
    ),
    "compile_current_workflow_launch_snapshot": (
        "banksia.definitions.registry.current",
        "compile_current_workflow_launch_snapshot",
    ),
    "load_current_policy": ("banksia.definitions.registry.current", "load_current_policy"),
    "load_current_role": ("banksia.definitions.registry.current", "load_current_role"),
    "load_current_workflow": ("banksia.definitions.registry.current", "load_current_workflow"),
    "load_policy_revision": ("banksia.definitions.registry.current", "load_policy_revision"),
    "load_role_revision": ("banksia.definitions.registry.current", "load_role_revision"),
    "seed_definition_registry": ("banksia.definitions.registry.seeds", "seed_definition_registry"),
    "upsert_policy_definition": (
        "banksia.definitions.registry.upsert",
        "upsert_policy_definition",
    ),
    "upsert_role_definition": ("banksia.definitions.registry.upsert", "upsert_role_definition"),
    "upsert_workflow_definition": (
        "banksia.definitions.registry.upsert",
        "upsert_workflow_definition",
    ),
}


def __getattr__(name: str) -> Any:
    module_name, attribute_name = _LAZY_EXPORTS.get(name, (None, None))
    if module_name is None or attribute_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "RegistryWorkflowDefinition",
    "build_role_policy_lookup",
    "compile_current_workflow",
    "compile_current_workflow_launch_snapshot",
    "load_current_policy",
    "load_current_role",
    "load_current_workflow",
    "load_policy_revision",
    "load_role_revision",
    "seed_definition_registry",
    "upsert_policy_definition",
    "upsert_role_definition",
    "upsert_workflow_definition",
]

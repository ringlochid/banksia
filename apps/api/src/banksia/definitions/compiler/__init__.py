from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from banksia.definitions.compiler.compile import compile_workflow
    from banksia.definitions.compiler.contracts import (
        DependencyKind,
        NormalizedChildDefaults,
        NormalizedCompiledNode,
        NormalizedCompiledPlan,
        NormalizedConsumeBuckets,
        NormalizedConsumeSelector,
        NormalizedCriteriaDeclaration,
        NormalizedDependencyEdge,
        NormalizedProduceBuckets,
        NormalizedProduceSlot,
        WorkflowRevisionMetadata,
    )
    from banksia.definitions.compiler.role_policy_lookup import (
        MappingRolePolicyLookup,
        PolicyRevisionDefinition,
        RolePolicyLookup,
        RoleRevisionDefinition,
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "DependencyKind": ("banksia.definitions.compiler.contracts", "DependencyKind"),
    "MappingRolePolicyLookup": (
        "banksia.definitions.compiler.role_policy_lookup",
        "MappingRolePolicyLookup",
    ),
    "NormalizedChildDefaults": (
        "banksia.definitions.compiler.contracts",
        "NormalizedChildDefaults",
    ),
    "NormalizedCompiledNode": ("banksia.definitions.compiler.contracts", "NormalizedCompiledNode"),
    "NormalizedCompiledPlan": ("banksia.definitions.compiler.contracts", "NormalizedCompiledPlan"),
    "NormalizedConsumeBuckets": (
        "banksia.definitions.compiler.contracts",
        "NormalizedConsumeBuckets",
    ),
    "NormalizedConsumeSelector": (
        "banksia.definitions.compiler.contracts",
        "NormalizedConsumeSelector",
    ),
    "NormalizedCriteriaDeclaration": (
        "banksia.definitions.compiler.contracts",
        "NormalizedCriteriaDeclaration",
    ),
    "NormalizedDependencyEdge": (
        "banksia.definitions.compiler.contracts",
        "NormalizedDependencyEdge",
    ),
    "NormalizedProduceBuckets": (
        "banksia.definitions.compiler.contracts",
        "NormalizedProduceBuckets",
    ),
    "NormalizedProduceSlot": ("banksia.definitions.compiler.contracts", "NormalizedProduceSlot"),
    "PolicyRevisionDefinition": (
        "banksia.definitions.compiler.role_policy_lookup",
        "PolicyRevisionDefinition",
    ),
    "RolePolicyLookup": ("banksia.definitions.compiler.role_policy_lookup", "RolePolicyLookup"),
    "RoleRevisionDefinition": (
        "banksia.definitions.compiler.role_policy_lookup",
        "RoleRevisionDefinition",
    ),
    "WorkflowRevisionMetadata": (
        "banksia.definitions.compiler.contracts",
        "WorkflowRevisionMetadata",
    ),
    "compile_workflow": ("banksia.definitions.compiler.compile", "compile_workflow"),
}


def __getattr__(name: str) -> Any:
    module_name, attribute_name = _LAZY_EXPORTS.get(name, (None, None))
    if module_name is None or attribute_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "DependencyKind",
    "MappingRolePolicyLookup",
    "NormalizedChildDefaults",
    "NormalizedCompiledNode",
    "NormalizedCompiledPlan",
    "NormalizedConsumeBuckets",
    "NormalizedConsumeSelector",
    "NormalizedCriteriaDeclaration",
    "NormalizedDependencyEdge",
    "NormalizedProduceBuckets",
    "NormalizedProduceSlot",
    "PolicyRevisionDefinition",
    "RolePolicyLookup",
    "RoleRevisionDefinition",
    "WorkflowRevisionMetadata",
    "compile_workflow",
]

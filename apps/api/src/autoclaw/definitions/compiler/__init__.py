from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from autoclaw.definitions.compiler.compile import compile_workflow
    from autoclaw.definitions.compiler.contracts import (
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
    from autoclaw.definitions.compiler.role_policy_lookup import (
        MappingRolePolicyLookup,
        PolicyRevisionDefinition,
        RolePolicyLookup,
        RoleRevisionDefinition,
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "DependencyKind": ("autoclaw.definitions.compiler.contracts", "DependencyKind"),
    "MappingRolePolicyLookup": (
        "autoclaw.definitions.compiler.role_policy_lookup",
        "MappingRolePolicyLookup",
    ),
    "NormalizedChildDefaults": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedChildDefaults",
    ),
    "NormalizedCompiledNode": ("autoclaw.definitions.compiler.contracts", "NormalizedCompiledNode"),
    "NormalizedCompiledPlan": ("autoclaw.definitions.compiler.contracts", "NormalizedCompiledPlan"),
    "NormalizedConsumeBuckets": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedConsumeBuckets",
    ),
    "NormalizedConsumeSelector": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedConsumeSelector",
    ),
    "NormalizedCriteriaDeclaration": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedCriteriaDeclaration",
    ),
    "NormalizedDependencyEdge": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedDependencyEdge",
    ),
    "NormalizedProduceBuckets": (
        "autoclaw.definitions.compiler.contracts",
        "NormalizedProduceBuckets",
    ),
    "NormalizedProduceSlot": ("autoclaw.definitions.compiler.contracts", "NormalizedProduceSlot"),
    "PolicyRevisionDefinition": (
        "autoclaw.definitions.compiler.role_policy_lookup",
        "PolicyRevisionDefinition",
    ),
    "RolePolicyLookup": ("autoclaw.definitions.compiler.role_policy_lookup", "RolePolicyLookup"),
    "RoleRevisionDefinition": (
        "autoclaw.definitions.compiler.role_policy_lookup",
        "RoleRevisionDefinition",
    ),
    "WorkflowRevisionMetadata": (
        "autoclaw.definitions.compiler.contracts",
        "WorkflowRevisionMetadata",
    ),
    "compile_workflow": ("autoclaw.definitions.compiler.compile", "compile_workflow"),
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

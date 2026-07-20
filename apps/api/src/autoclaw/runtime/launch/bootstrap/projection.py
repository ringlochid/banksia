from __future__ import annotations

from pathlib import Path

from autoclaw.definitions.compiler import NormalizedCompiledNode, NormalizedCompiledPlan
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts import (
    AssignmentProjection,
    EvidenceKind,
    EvidenceRef,
    ProduceRequirement,
    ResolvedNodeContext,
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
    TaskRootPaths,
)
from autoclaw.runtime.errors import illegal_state_error, missing_resource_error
from autoclaw.runtime.ids import assignment_id, flow_id_for_task
from autoclaw.runtime.launch.bootstrap.criteria import (
    build_launch_criteria_projection_signals,
)
from autoclaw.runtime.projection.signals import (
    AttemptAssignmentProjection,
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from autoclaw.runtime.task_root import criteria_logical_path, resolve_task_root_paths


def build_launch_bootstrap_result(
    bootstrap_input: RuntimeBootstrapInput,
) -> RuntimeBootstrapResult:
    """Build fresh-task controller records without opening or projecting a dispatch."""

    task_root_paths = resolve_task_root_paths(
        task_root=bootstrap_input.task_root,
        task_compose=bootstrap_input.task_compose,
    )
    criteria_paths = _criteria_paths(
        bootstrap_input,
        task_root_paths=task_root_paths,
    )
    current_node = _resolve_root_node_context(bootstrap_input)
    assignment = _build_launch_assignment(
        bootstrap_input=bootstrap_input,
        current_node=current_node,
        criteria_paths=criteria_paths,
        criteria_descriptions=_criteria_descriptions_by_slot(bootstrap_input.compiled_plan),
    )
    return RuntimeBootstrapResult(paths=task_root_paths, assignment=assignment)


def build_launch_support_projection_signals(
    bootstrap_input: RuntimeBootstrapInput,
) -> tuple[SupportProjectionSignal, ...]:
    """Expose post-commit launch projections without coupling launch to the owner."""

    return (
        WorkflowManifestProjection(
            flow_id=flow_id_for_task(bootstrap_input.task_id),
            active_flow_revision_id=bootstrap_input.active_flow_revision_id,
        ),
        *build_launch_criteria_projection_signals(
            flow_revision_id=bootstrap_input.active_flow_revision_id,
            nodes=bootstrap_input.compiled_plan.nodes,
        ),
        AttemptAssignmentProjection(
            assignment_id=assignment_id(bootstrap_input.assignment_key),
            attempt_id=bootstrap_input.attempt_id,
            flow_revision_id=bootstrap_input.active_flow_revision_id,
        ),
    )


def _compiled_nodes_by_key(
    compiled_plan: NormalizedCompiledPlan,
) -> dict[str, NormalizedCompiledNode]:
    return {node.node_key: node for node in compiled_plan.nodes}


def _criteria_descriptions_by_slot(compiled_plan: NormalizedCompiledPlan) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for node in compiled_plan.nodes:
        for criteria in node.criteria:
            descriptions[criteria.slot] = criteria.description
    return descriptions


def _merge_criteria_refs(
    *criteria_groups: tuple[EvidenceRef, ...],
) -> tuple[EvidenceRef, ...]:
    merged: list[EvidenceRef] = []
    seen_slots: set[str] = set()
    for group in criteria_groups:
        for ref in group:
            if ref.slot is None:
                merged.append(ref)
                continue
            if ref.slot in seen_slots:
                continue
            seen_slots.add(ref.slot)
            merged.append(ref)
    return tuple(merged)


def _resolve_root_node_context(
    bootstrap_input: RuntimeBootstrapInput,
) -> ResolvedNodeContext:
    root_node_key = bootstrap_input.workflow_definition.root.node_key
    compiled_node = _compiled_nodes_by_key(bootstrap_input.compiled_plan).get(root_node_key)
    if compiled_node is None:
        raise illegal_state_error(f"compiled plan is missing authored root node '{root_node_key}'")
    if compiled_node.structural_kind != NodeKind.ROOT or compiled_node.parent_node_key is not None:
        raise illegal_state_error(f"compiled node '{root_node_key}' is not the structural root")

    role_revision = bootstrap_input.role_policy_lookup.get_role(compiled_node.role)
    if role_revision is None:
        raise missing_resource_error(f"missing role definition for '{compiled_node.role}'")

    policy_revision = bootstrap_input.role_policy_lookup.get_policy(compiled_node.policy)
    if policy_revision is None:
        raise missing_resource_error(f"missing policy definition for '{compiled_node.policy}'")

    return ResolvedNodeContext(
        node_key=compiled_node.node_key,
        node_kind=compiled_node.structural_kind,
        node_description=compiled_node.description,
        node_instruction=compiled_node.node_instruction,
        role_key=compiled_node.role,
        role_revision_no=compiled_node.role_revision_no,
        role_description=role_revision.definition.description,
        role_instruction=role_revision.definition.instruction,
        policy_key=compiled_node.policy,
        policy_revision_no=compiled_node.policy_revision_no,
        policy_description=policy_revision.definition.description,
        policy_instruction=policy_revision.definition.instruction,
    )


def _build_launch_assignment(
    *,
    bootstrap_input: RuntimeBootstrapInput,
    current_node: ResolvedNodeContext,
    criteria_paths: dict[str, Path],
    criteria_descriptions: dict[str, str],
) -> AssignmentProjection:
    compiled_node = _compiled_nodes_by_key(bootstrap_input.compiled_plan)[current_node.node_key]
    if compiled_node.consumes is not None and compiled_node.consumes.artifacts:
        raise illegal_state_error(
            "the root assignment cannot consume an unresolved artifact at task start",
            suggested_next_step=(
                "Remove root artifact consumption or start from a workflow whose root inputs "
                "are available from controller truth."
            ),
        )

    criteria_refs = tuple(
        EvidenceRef(
            kind=EvidenceKind.CRITERIA,
            slot=criteria.slot,
            path=criteria_paths[criteria.slot],
            description=criteria.description,
        )
        for criteria in compiled_node.criteria
    )
    selector_criteria_refs = tuple(
        EvidenceRef(
            kind=EvidenceKind.CRITERIA,
            slot=selector.slot,
            path=criteria_paths[selector.slot],
            description=criteria_descriptions[selector.slot],
        )
        for selector in (compiled_node.consumes.criteria if compiled_node.consumes else ())
    )
    produces = tuple(
        ProduceRequirement(
            slot=artifact.slot,
            description=artifact.description,
            file_hint=artifact.file_hint,
        )
        for artifact in (compiled_node.produces.artifacts if compiled_node.produces else ())
    )

    instruction_parts = []
    if bootstrap_input.task_compose.task.instruction is not None:
        instruction_parts.append(bootstrap_input.task_compose.task.instruction)
    instruction_parts.append(f"Node purpose: {current_node.node_description}")
    if current_node.node_instruction is not None:
        instruction_parts.append(f"Node instruction: {current_node.node_instruction}")
    instruction_parts.append(f"Role guidance: {current_node.role_description}")
    if current_node.role_instruction is not None:
        instruction_parts.append(current_node.role_instruction)
    if current_node.policy_description is not None:
        instruction_parts.append(f"Policy guidance: {current_node.policy_description}")
    if current_node.policy_instruction is not None:
        instruction_parts.append(current_node.policy_instruction)

    return AssignmentProjection(
        assignment_key=bootstrap_input.assignment_key,
        node_key=current_node.node_key,
        summary=bootstrap_input.task_compose.task.summary,
        instruction="\n".join(instruction_parts).strip() or None,
        criteria=_merge_criteria_refs(criteria_refs, selector_criteria_refs),
        consumes=(),
        produces=produces,
    )


def _criteria_paths(
    bootstrap_input: RuntimeBootstrapInput,
    *,
    task_root_paths: TaskRootPaths,
) -> dict[str, Path]:
    return {
        criteria.slot: criteria_logical_path(slot=criteria.slot, version=1)
        for node in bootstrap_input.compiled_plan.nodes
        for criteria in node.criteria
    }


__all__ = ["build_launch_bootstrap_result", "build_launch_support_projection_signals"]

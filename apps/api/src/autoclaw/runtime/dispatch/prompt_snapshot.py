from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts.capabilities import EffectiveCapabilitySet
from autoclaw.runtime.contracts.primitives import CapabilityDecision
from autoclaw.runtime.contracts.prompt import (
    AcceptedBoundaryTrigger,
    ChildReturnTrigger,
    CommandResultTrigger,
    DispatchRequestRenderInput,
    HumanResultTrigger,
    OperatorContinueTrigger,
    PromptAssignment,
    PromptAssignmentBudget,
    PromptContext,
    PromptCriterion,
    PromptDispatch,
    PromptDynamicInput,
    PromptFamily,
    PromptInstructionGuidance,
    PromptLogicalRef,
    PromptNext,
    PromptRefKind,
    PromptSlot,
    PromptWorkflowNeighbor,
    RootStartTrigger,
    RuntimeReadbackRefs,
    SemanticRetryTrigger,
    WatchdogRecoveryTrigger,
    prompt_family_for_node_kind,
)
from autoclaw.runtime.work_plan import WorkPlanRead


@dataclass(frozen=True, slots=True)
class RootPromptChildSnapshot:
    node_key: str
    node_kind: str
    assignment_id: str | None


@dataclass(frozen=True, slots=True)
class RootPromptSnapshot:
    task_id: str
    task_title: str
    task_summary: str
    task_instruction: str | None
    workflow_key: str
    workflow_revision_no: int
    workflow_description: str | None
    flow_id: str
    flow_revision_id: str
    dispatch_id: str
    assignment_id: str
    attempt_id: str
    retry_of_attempt_id: str | None
    node_key: str
    role_key: str
    role_description: str
    role_instruction: str | None
    policy_description: str
    policy_instruction: str | None
    node_description: str
    node_instruction: str | None
    assignment_summary: str
    assignment_instruction: str | None
    criteria_json: tuple[dict[str, object], ...]
    consumes_json: tuple[dict[str, object], ...]
    produces_json: tuple[dict[str, object], ...]
    child_assignment_limit: int | None
    child_assignments_remaining: int | None
    retry_limit: int | None
    retries_remaining: int | None
    work_plan: WorkPlanRead | None
    capabilities: EffectiveCapabilitySet
    children: tuple[RootPromptChildSnapshot, ...]


type BoundaryPromptTrigger = AcceptedBoundaryTrigger | ChildReturnTrigger | SemanticRetryTrigger
type OrdinaryPromptTrigger = (
    HumanResultTrigger | CommandResultTrigger | WatchdogRecoveryTrigger | OperatorContinueTrigger
)
type RootPromptTrigger = RootStartTrigger | OperatorContinueTrigger


@dataclass(frozen=True, slots=True)
class BoundaryPromptSnapshot(RootPromptSnapshot):
    node_kind: str
    parent_assignment_id: str | None
    predecessor_dispatch_id: str
    trigger: BoundaryPromptTrigger


@dataclass(frozen=True, slots=True)
class OrdinaryPromptSnapshot(RootPromptSnapshot):
    node_kind: str
    parent_assignment_id: str | None
    predecessor_dispatch_id: str
    trigger: OrdinaryPromptTrigger


type ContinuationPromptSnapshot = BoundaryPromptSnapshot | OrdinaryPromptSnapshot


def build_root_dispatch_request(
    snapshot: RootPromptSnapshot,
    *,
    trigger: RootPromptTrigger | None = None,
) -> DispatchRequestRenderInput:
    criteria = _criteria(snapshot.criteria_json)
    consume_slots, refs = _consume_slots(snapshot.consumes_json)
    allowed_actions = _root_start_actions(snapshot)
    exact_trigger = trigger or RootStartTrigger(flow_id=snapshot.flow_id)
    workflow_guidance = _texts(
        snapshot.workflow_description,
        f"Task: {snapshot.task_title}. {snapshot.task_summary}",
        snapshot.task_instruction,
    )
    return DispatchRequestRenderInput(
        family=PromptFamily.PARENT_ROOT,
        guidance=PromptInstructionGuidance(
            workflow=workflow_guidance,
            role=_texts(snapshot.role_description, snapshot.role_instruction),
            node=_texts(snapshot.node_description, snapshot.node_instruction),
            policy=_texts(snapshot.policy_description, snapshot.policy_instruction),
        ),
        dynamic_input=PromptDynamicInput(
            assignment=PromptAssignment(
                assignment_id=snapshot.assignment_id,
                role_id=snapshot.role_key,
                role_description=snapshot.role_description,
                node_kind=NodeKind.ROOT,
                summary=snapshot.assignment_summary,
                instruction=snapshot.assignment_instruction,
                criteria=criteria,
                consume_slots=consume_slots,
                produce_slots=_produce_slots(snapshot.produces_json),
                budget=PromptAssignmentBudget(
                    child_assignment_limit=snapshot.child_assignment_limit,
                    child_assignments_remaining=snapshot.child_assignments_remaining,
                    retry_limit=snapshot.retry_limit,
                    retries_remaining=snapshot.retries_remaining,
                ),
            ),
            trigger=exact_trigger,
            plan=snapshot.work_plan,
            context=PromptContext(
                capabilities=snapshot.capabilities,
                allowed_actions=allowed_actions,
                workflow_neighborhood=tuple(
                    PromptWorkflowNeighbor(
                        node_key=child.node_key,
                        node_kind=NodeKind(child.node_kind),
                        relationship="direct child",
                        assignment_id=child.assignment_id,
                    )
                    for child in snapshot.children
                ),
                readback_refs=_runtime_readback_refs(snapshot.dispatch_id),
                refs=refs,
                constraints=(
                    "Treat controller-owned MCP state as runtime truth.",
                    "Stay within the current root assignment and surfaced logical refs.",
                ),
            ),
            dispatch=PromptDispatch(
                task_id=snapshot.task_id,
                flow_id=snapshot.flow_id,
                flow_revision_id=snapshot.flow_revision_id,
                dispatch_id=snapshot.dispatch_id,
                assignment_id=snapshot.assignment_id,
                attempt_id=snapshot.attempt_id,
                node_key=snapshot.node_key,
                node_kind=NodeKind.ROOT,
                retry_of_attempt_id=snapshot.retry_of_attempt_id,
            ),
            next=PromptNext(
                instruction=_root_trigger_instruction(exact_trigger),
                inspect_refs=refs,
            ),
        ),
    )


def build_boundary_dispatch_request(
    snapshot: BoundaryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_continuation_dispatch_request(
        snapshot,
        next_instruction=_boundary_trigger_instruction(snapshot.trigger),
        source_constraint="Act only on the exact accepted-boundary continuation shown here.",
    )


def build_ordinary_dispatch_request(
    snapshot: OrdinaryPromptSnapshot,
) -> DispatchRequestRenderInput:
    return _build_continuation_dispatch_request(
        snapshot,
        next_instruction=_ordinary_trigger_instruction(snapshot.trigger),
        source_constraint="Act only on the exact continuation source shown here.",
    )


def _build_continuation_dispatch_request(
    snapshot: ContinuationPromptSnapshot,
    *,
    next_instruction: str,
    source_constraint: str,
) -> DispatchRequestRenderInput:
    node_kind = NodeKind(snapshot.node_kind)
    criteria = _criteria(snapshot.criteria_json)
    consume_slots, refs = _consume_slots(snapshot.consumes_json)
    return DispatchRequestRenderInput(
        family=prompt_family_for_node_kind(node_kind),
        guidance=PromptInstructionGuidance(
            workflow=_texts(
                snapshot.workflow_description,
                f"Task: {snapshot.task_title}. {snapshot.task_summary}",
                snapshot.task_instruction,
            ),
            role=_texts(snapshot.role_description, snapshot.role_instruction),
            node=_texts(snapshot.node_description, snapshot.node_instruction),
            policy=_texts(snapshot.policy_description, snapshot.policy_instruction),
        ),
        dynamic_input=PromptDynamicInput(
            assignment=PromptAssignment(
                assignment_id=snapshot.assignment_id,
                role_id=snapshot.role_key,
                role_description=snapshot.role_description,
                node_kind=node_kind,
                summary=snapshot.assignment_summary,
                instruction=snapshot.assignment_instruction,
                criteria=criteria,
                consume_slots=consume_slots,
                produce_slots=_produce_slots(snapshot.produces_json),
                budget=PromptAssignmentBudget(
                    child_assignment_limit=snapshot.child_assignment_limit,
                    child_assignments_remaining=snapshot.child_assignments_remaining,
                    retry_limit=snapshot.retry_limit,
                    retries_remaining=snapshot.retries_remaining,
                ),
            ),
            trigger=snapshot.trigger,
            plan=snapshot.work_plan,
            context=PromptContext(
                capabilities=snapshot.capabilities,
                allowed_actions=_boundary_actions(snapshot, node_kind=node_kind),
                workflow_neighborhood=tuple(
                    PromptWorkflowNeighbor(
                        node_key=child.node_key,
                        node_kind=NodeKind(child.node_kind),
                        relationship="direct child",
                        assignment_id=child.assignment_id,
                    )
                    for child in snapshot.children
                ),
                readback_refs=_runtime_readback_refs(snapshot.dispatch_id),
                refs=refs,
                constraints=(
                    "Treat controller-owned MCP state as runtime truth.",
                    source_constraint,
                ),
            ),
            dispatch=PromptDispatch(
                task_id=snapshot.task_id,
                flow_id=snapshot.flow_id,
                flow_revision_id=snapshot.flow_revision_id,
                dispatch_id=snapshot.dispatch_id,
                assignment_id=snapshot.assignment_id,
                attempt_id=snapshot.attempt_id,
                node_key=snapshot.node_key,
                node_kind=node_kind,
                parent_assignment_id=snapshot.parent_assignment_id,
                retry_of_attempt_id=snapshot.retry_of_attempt_id,
                predecessor_dispatch_id=snapshot.predecessor_dispatch_id,
            ),
            next=PromptNext(
                instruction=next_instruction,
                inspect_refs=refs,
            ),
        ),
    )


def _criteria(rows: tuple[dict[str, object], ...]) -> tuple[PromptCriterion, ...]:
    criteria: list[PromptCriterion] = []
    for row in rows:
        checks = row.get("criteria")
        if not isinstance(checks, list) or not checks:
            raise ValueError("root criteria require a nonempty criteria list")
        criteria.append(
            PromptCriterion(
                slot=_required_text(row, "slot"),
                description=_required_text(row, "description"),
                checks=tuple(_required_list_text(checks)),
                logical_path=_optional_text(row.get("path")),
            )
        )
    return tuple(criteria)


def _runtime_readback_refs(dispatch_id: str) -> RuntimeReadbackRefs:
    dispatch_root = f"_runtime/dispatch/{dispatch_id}"
    return RuntimeReadbackRefs(
        instructions=f"{dispatch_root}/instructions.md",
        input=f"{dispatch_root}/input.md",
        workflow_manifest="_runtime/workflow-manifest.md",
    )


def _consume_slots(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[PromptSlot, ...], tuple[PromptLogicalRef, ...]]:
    slots: list[PromptSlot] = []
    refs: list[PromptLogicalRef] = []
    for row in rows:
        kind = _prompt_ref_kind(row.get("kind"))
        path = _optional_text(row.get("path"))
        description = _required_text(row, "description")
        if kind is None or path is None:
            continue
        slot = _optional_text(row.get("slot"))
        version = _optional_positive_int(row.get("version"))
        if kind == PromptRefKind.ARTIFACT and (slot is None or version is None):
            raise ValueError("artifact consume refs require slot and version")
        slots.append(
            PromptSlot(
                slot=slot or path,
                kind=kind,
                description=description,
                logical_path=path,
                version=version if kind == PromptRefKind.ARTIFACT else None,
            )
        )
        refs.append(
            PromptLogicalRef(
                kind=kind,
                logical_path=path,
                purpose="Inspect this input before acting on the assignment.",
                description=description,
                slot=slot,
                version=version if kind == PromptRefKind.ARTIFACT else None,
            )
        )
    return tuple(slots), tuple(refs)


def _produce_slots(rows: tuple[dict[str, object], ...]) -> tuple[PromptSlot, ...]:
    return tuple(
        PromptSlot(
            slot=_required_text(row, "slot"),
            kind=PromptRefKind.ARTIFACT,
            description=_required_text(row, "description"),
        )
        for row in rows
    )


def _root_start_actions(snapshot: RootPromptSnapshot) -> tuple[str, ...]:
    actions = {
        "release_blocked",
        "release_green",
        "get_current_context",
        "list_files",
        "read_file",
        "return_boundary",
        "set_work_plan",
        "record_checkpoint",
        "search_definitions",
        "get_definition",
        "add_child",
    }
    if any(child.assignment_id is None for child in snapshot.children):
        actions.add("assign_child")
    if snapshot.children:
        actions.update(("update_child", "remove_child"))
    human = snapshot.capabilities.human_request
    if CapabilityDecision.ALLOW in {
        human.direction,
        human.approval,
        human.input,
        human.review,
    }:
        actions.add("open_human_request")
    if snapshot.capabilities.command_run == CapabilityDecision.ALLOW:
        actions.add("start_command_run")
    return tuple(sorted(actions))


def _boundary_actions(
    snapshot: ContinuationPromptSnapshot,
    *,
    node_kind: NodeKind,
) -> tuple[str, ...]:
    actions = {
        "get_current_context",
        "list_files",
        "read_file",
        "set_work_plan",
        "record_checkpoint",
        "return_boundary",
    }
    if node_kind != NodeKind.WORKER:
        actions.update(("search_definitions", "get_definition", "add_child", "release_green"))
        if node_kind == NodeKind.ROOT:
            actions.add("release_blocked")
        if any(child.assignment_id is None for child in snapshot.children):
            actions.add("assign_child")
        if snapshot.children:
            actions.update(("update_child", "remove_child"))
    human = snapshot.capabilities.human_request
    if CapabilityDecision.ALLOW in {
        human.direction,
        human.approval,
        human.input,
        human.review,
    }:
        actions.add("open_human_request")
    if snapshot.capabilities.command_run == CapabilityDecision.ALLOW:
        actions.add("start_command_run")
    return tuple(sorted(actions))


def _boundary_trigger_instruction(trigger: BoundaryPromptTrigger) -> str:
    if isinstance(trigger, AcceptedBoundaryTrigger):
        return "Begin the exact child assignment activated by the accepted yield boundary."
    if isinstance(trigger, SemanticRetryTrigger):
        return (
            "Read the retry checkpoint identified by the trigger, then continue the "
            "assignment as the new semantic attempt."
        )
    return (
        "Read the child checkpoint identified by the trigger, then review and integrate "
        "that exact child return."
    )


def _ordinary_trigger_instruction(trigger: OrdinaryPromptTrigger) -> str:
    if isinstance(trigger, HumanResultTrigger):
        return (
            "Read the exact human-request result in the trigger, then continue the same "
            "assignment and attempt."
        )
    if isinstance(trigger, CommandResultTrigger):
        return (
            "Read the exact command result and its logical refs, then continue the same "
            "assignment and attempt."
        )
    if isinstance(trigger, WatchdogRecoveryTrigger):
        return (
            "Resume the same assignment and attempt from controller-owned context after "
            "the exact predecessor dispatch became inactive."
        )
    return (
        "Reread the current controller context, honor the recorded pause reason, and "
        "continue from the exact operator-selected source."
    )


def _root_trigger_instruction(trigger: RootPromptTrigger) -> str:
    if isinstance(trigger, RootStartTrigger):
        return (
            "Read the current controller context, maintain an explicit work plan "
            "when useful, and execute the root assignment."
        )
    return (
        "Reread the current controller context, honor the recorded pause reason, and "
        "begin the root assignment from the exact retained flow-start source."
    )


def _prompt_ref_kind(value: object) -> PromptRefKind | None:
    if value in {"artifact", "criteria", "transient"}:
        return PromptRefKind(str(value))
    if value in {"doc", "wiki"}:
        return PromptRefKind.WORKSPACE
    return None


def _texts(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value is not None and value.strip())


def _required_text(row: dict[str, object], key: str) -> str:
    value = _optional_text(row.get(key))
    if value is None:
        raise ValueError(f"root prompt row requires nonempty '{key}'")
    return value


def _required_list_text(values: list[Any]) -> tuple[str, ...]:
    normalized = tuple(_optional_text(value) for value in values)
    if any(value is None for value in normalized):
        raise ValueError("root prompt list values must be nonempty strings")
    return tuple(value for value in normalized if value is not None)


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


__all__ = [
    "BoundaryPromptSnapshot",
    "BoundaryPromptTrigger",
    "ContinuationPromptSnapshot",
    "OrdinaryPromptSnapshot",
    "OrdinaryPromptTrigger",
    "RootPromptChildSnapshot",
    "RootPromptSnapshot",
    "RootPromptTrigger",
    "build_boundary_dispatch_request",
    "build_ordinary_dispatch_request",
    "build_root_dispatch_request",
]

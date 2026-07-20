from __future__ import annotations


def flow_id_for_task(task_id: str) -> str:
    return f"flow.{task_id}"


def task_compose_id_for_task(task_id: str) -> str:
    return f"task-compose.{task_id}"


def compiled_plan_id_for_task(task_id: str) -> str:
    return f"compiled-plan.{task_id}"


def assignment_criteria_ref_id(assignment_id: str, slot: str) -> str:
    return f"assignment-criteria-ref.{assignment_id}.{slot}"


def compiled_plan_node_id(compiled_plan_id: str, node_key: str) -> str:
    return f"compiled-plan-node.{compiled_plan_id}.{node_key}"


def compiled_plan_edge_id(
    compiled_plan_id: str,
    consumer_node_key: str,
    dependency_kind: str,
    slot: str,
) -> str:
    return f"compiled-plan-edge.{compiled_plan_id}.{consumer_node_key}.{dependency_kind}.{slot}"


def flow_node_id(flow_revision_id: str, node_key: str) -> str:
    return f"flow-node.{flow_revision_id}.{node_key}"


def flow_edge_id(
    flow_revision_id: str, consumer_node_key: str, dependency_kind: str, slot: str
) -> str:
    return f"flow-edge.{flow_revision_id}.{consumer_node_key}.{dependency_kind}.{slot}"


def node_plan_revision_id(flow_revision_id: str, node_key: str) -> str:
    return f"node-plan-revision.{flow_revision_id}.{node_key}"


def assignment_id(assignment_key: str) -> str:
    return f"assignment.{assignment_key}"


def assignment_key_for_task(task_id: str, node_key: str, sequence: int) -> str:
    return f"{task_id}.{node_key}.assign-{sequence:02d}"


def checkpoint_id(attempt_id: str, sequence: int) -> str:
    return f"checkpoint.{attempt_id}.{sequence:02d}"


def artifact_publication_id(attempt_id: str, slot: str, version: int) -> str:
    return f"artifact-publication.{attempt_id}.{slot}.v{version:02d}"


def artifact_current_pointer_id(task_id: str, owner_node_key: str, slot: str) -> str:
    return f"artifact-current-pointer.{task_id}.{owner_node_key}.{slot}"


def task_event_id(task_id: str, event_seq: int) -> str:
    return f"task-event.{task_id}.{event_seq:08d}"


def human_request_id(task_id: str, sequence: int) -> str:
    return f"human-request.{task_id}.{sequence:04d}"


def command_run_id(task_id: str, sequence: int) -> str:
    return f"command-run.{task_id}.{sequence:04d}"


def flow_revision_id(flow_id: str, revision_index: int) -> str:
    return f"flow-revision.{flow_id}.{revision_index:02d}"


def dispatch_id(node_key: str, sequence: int) -> str:
    return f"dispatch.{node_key}.{sequence:02d}"


def attempt_id(node_key: str, sequence: int) -> str:
    return f"attempt.{node_key}.{sequence:02d}"


def attempt_id_for_task(task_id: str, node_key: str, sequence: int) -> str:
    return f"attempt.{task_id}.{node_key}.{sequence:02d}"

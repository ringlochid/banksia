from __future__ import annotations


def flow_id_for_task(task_id: str) -> str:
    return f"flow.{task_id}"


def compiled_plan_id_for_task(task_id: str) -> str:
    return f"compiled-plan.{task_id}"


def compiled_plan_node_id(compiled_plan_id: str, node_key: str) -> str:
    return f"compiled-plan-node.{compiled_plan_id}.{node_key}"


def flow_node_id(flow_revision_id: str, node_key: str) -> str:
    return f"flow-node.{flow_revision_id}.{node_key}"


def node_plan_revision_id(flow_revision_id: str, node_key: str) -> str:
    return f"node-plan-revision.{flow_revision_id}.{node_key}"


def assignment_id(assignment_key: str) -> str:
    return f"assignment.{assignment_key}"


def assignment_key_for_task(task_id: str, node_key: str, sequence: int) -> str:
    return f"{task_id}.{node_key}.assign-{sequence:02d}"


def task_event_id(task_id: str, event_seq: int) -> str:
    return f"task-event.{task_id}.{event_seq:08d}"


def flow_revision_id(flow_id: str, revision_index: int) -> str:
    return f"flow-revision.{flow_id}.{revision_index:02d}"


def attempt_id_for_task(task_id: str, node_key: str, sequence: int) -> str:
    return f"attempt.{task_id}.{node_key}.{sequence:02d}"

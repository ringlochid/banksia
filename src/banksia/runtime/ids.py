from __future__ import annotations


def assignment_id_for_task(task_id: str, member_id: str, sequence: int) -> str:
    return f"assignment.{task_id}.{member_id}.assign-{sequence:02d}"


def task_event_id(task_id: str, event_seq: int) -> str:
    return f"task-event.{task_id}.{event_seq:08d}"


def attempt_id_for_task(task_id: str, member_id: str, sequence: int) -> str:
    return f"attempt.{task_id}.{member_id}.{sequence:02d}"

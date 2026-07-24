from __future__ import annotations

from datetime import UTC, datetime

NODE_KIND_VALUES = ("root", "parent", "worker")
NODE_STATE_VALUES = (
    "ready",
    "running",
    "waiting",
    "paused",
    "done",
    "failed",
    "superseded",
    "cancelled",
)
FLOW_STATUS_VALUES = ("running", "paused", "completed", "cancelled")
FLOW_TERMINAL_OUTCOME_VALUES = ("green", "blocked")
STRUCTURAL_REVISION_CAUSE_VALUES = ("launch", "add_child", "update_child", "remove_child")
REPLAN_OPERATION_VALUES = ("add_child", "update_child", "remove_child")
REPLAN_MANIFEST_STATE_VALUES = ("pending", "repair_required", "current")
REPLAN_SUCCESSOR_STATE_VALUES = (
    "blocked",
    "pending",
    "opening_failed",
    "opened",
    "cancelled",
)
CHECKPOINT_OUTCOME_VALUES = ("green", "retry", "blocked")
ATTEMPT_STATUS_VALUES = (
    "pending",
    "running",
    "completed",
    "cancelled",
)
DISPATCH_STATUS_VALUES = ("starting", "open", "closed")
DISPATCH_OPENED_REASON_VALUES = (
    "root",
    "boundary",
    "child_return",
    "human_result",
    "command_result",
    "watchdog_recovery",
    "semantic_retry",
    "operator_continue",
    "structural_replan",
)
DISPATCH_CLOSED_REASON_VALUES = (
    "boundary",
    "human_request_wait",
    "command_run_wait",
    "watchdog_superseded",
    "paused",
    "cancelled",
    "control_failed",
    "task_terminal",
    "structural_replan",
)
DISPATCH_STARTING_CLOSE_REASON_VALUES = (
    "boundary",
    "human_request_wait",
    "command_run_wait",
    "paused",
    "cancelled",
    "control_failed",
    "task_terminal",
    "structural_replan",
)
PROVIDER_VALUES = ("codex", "claude", "openclaw")
PROVIDER_SELECTION_BASIS_VALUES = ("explicit", "default")
PROVIDER_ROUTE_VALUE_SOURCE_VALUES = ("member_configuration", "provider_configuration")
PROVIDER_START_RETRY_KIND_VALUES = (
    "initial",
    "definite_failure",
    "uncertain_acceptance",
)
PROVIDER_NATIVE_ACCESS_VALUES = ("full", "restricted", "denied")
NETWORK_ACCESS_VALUES = ("allow", "deny")
MANAGED_SANDBOX_MODE_VALUES = ("read_only", "workspace_write", "full_access")
CAPABILITY_SOURCE_VALUES = ("default", "member_configuration", "controller")
CAPABILITY_DECISION_VALUES = ("allow", "deny")
BOUNDARY_OUTCOME_VALUES = ("yield", "green", "retry", "blocked")
WORK_PLAN_STEP_STATUS_VALUES = ("pending", "in_progress", "completed")
WORKSPACE_BINDING_MODE_VALUES = ("controller_owned", "external")
HUMAN_REQUEST_KIND_VALUES = ("direction", "approval", "input", "review")
HUMAN_REQUEST_STATUS_VALUES = ("open", "resolved", "timed_out", "cancelled")
HUMAN_REQUEST_RESOLUTION_KIND_VALUES = ("answered", "timed_out", "cancelled")
HUMAN_REQUEST_RESOLUTION_SURFACE_VALUES = (
    "control_api",
    "control_ui",
    "operator_mcp",
    "controller",
)
COMMAND_RUN_STATE_VALUES = (
    "pending_start",
    "running",
    "cancellation_requested",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "abandoned",
)
COMMAND_RUN_TERMINAL_STATE_VALUES = (
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "abandoned",
)
COMMAND_RUN_TERMINAL_SOURCE_VALUES = (
    "controller",
    "control_api",
    "operator_mcp",
    "process_owner",
)
TASK_EVENT_SOURCE_VALUES = ("controller", "control_api", "operator_mcp", "node")
TASK_EVENT_TYPE_VALUES = (
    "task_started",
    "dispatch_opened",
    "dispatch_start_updated",
    "work_plan_set",
    "work_plan_cleared",
    "checkpoint_recorded",
    "boundary_accepted",
    "child_assignment_staged",
    "child_assignment_committed",
    "structural_revision_adopted",
    "human_request_opened",
    "human_request_resolved",
    "human_request_timed_out",
    "human_request_cancelled",
    "command_run_opened",
    "command_run_started",
    "command_run_progressed",
    "command_run_cancel_requested",
    "command_run_succeeded",
    "command_run_failed",
    "command_run_timed_out",
    "command_run_cancelled",
    "command_run_abandoned",
    "task_paused",
    "task_resumed",
    "task_cancelled",
)


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


__all__ = [
    "ATTEMPT_STATUS_VALUES",
    "BOUNDARY_OUTCOME_VALUES",
    "CAPABILITY_DECISION_VALUES",
    "CAPABILITY_SOURCE_VALUES",
    "CHECKPOINT_OUTCOME_VALUES",
    "COMMAND_RUN_STATE_VALUES",
    "COMMAND_RUN_TERMINAL_SOURCE_VALUES",
    "COMMAND_RUN_TERMINAL_STATE_VALUES",
    "DISPATCH_CLOSED_REASON_VALUES",
    "DISPATCH_OPENED_REASON_VALUES",
    "DISPATCH_STARTING_CLOSE_REASON_VALUES",
    "DISPATCH_STATUS_VALUES",
    "FLOW_STATUS_VALUES",
    "FLOW_TERMINAL_OUTCOME_VALUES",
    "HUMAN_REQUEST_KIND_VALUES",
    "HUMAN_REQUEST_RESOLUTION_KIND_VALUES",
    "HUMAN_REQUEST_RESOLUTION_SURFACE_VALUES",
    "HUMAN_REQUEST_STATUS_VALUES",
    "MANAGED_SANDBOX_MODE_VALUES",
    "NETWORK_ACCESS_VALUES",
    "NODE_KIND_VALUES",
    "NODE_STATE_VALUES",
    "PROVIDER_NATIVE_ACCESS_VALUES",
    "PROVIDER_ROUTE_VALUE_SOURCE_VALUES",
    "PROVIDER_SELECTION_BASIS_VALUES",
    "PROVIDER_START_RETRY_KIND_VALUES",
    "PROVIDER_VALUES",
    "REPLAN_MANIFEST_STATE_VALUES",
    "REPLAN_OPERATION_VALUES",
    "REPLAN_SUCCESSOR_STATE_VALUES",
    "STRUCTURAL_REVISION_CAUSE_VALUES",
    "TASK_EVENT_SOURCE_VALUES",
    "TASK_EVENT_TYPE_VALUES",
    "WORKSPACE_BINDING_MODE_VALUES",
    "WORK_PLAN_STEP_STATUS_VALUES",
    "sql_in",
    "utcnow",
]

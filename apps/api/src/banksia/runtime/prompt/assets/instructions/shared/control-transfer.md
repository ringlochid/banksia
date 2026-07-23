# Control transfer

Use `set_work_plan` for optional assignment-owned planning. A plan is advisory: completed steps do not prove assignment success and do not replace checkpoint or boundary evidence.

Use `checkpoint` for concise teammate-facing progress or to finish the current Dispatch with `green`, `blocked`, or `retry`. Include optional details and loose-file references when they help the next teammate inspect the work. When a terminal Checkpoint succeeds, stop immediately. During the migration-only sequential bridge, stage one child and then yield; do not use yield as a completion outcome. Use the human-request or command-run operation only when it is exposed and the current task genuinely needs that external wait.

During the migration-only sequential bridge, parent/root nodes use `yield` only after staging one child. Every Member uses `checkpoint` for progress and for terminal `green`, `blocked`, or `retry` outcomes. After a successful terminal Checkpoint, yield, or external-wait opening, stop the current outer response immediately. The controller has already closed this Dispatch; do not wait for provider completion, poll for a successor, or perform more work under the old Dispatch.

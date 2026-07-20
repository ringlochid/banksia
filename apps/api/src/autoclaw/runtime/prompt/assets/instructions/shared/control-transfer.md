# Control transfer

Use `set_work_plan` for optional assignment-owned planning. A plan is advisory: completed steps do not prove assignment success and do not replace checkpoint or boundary evidence.

Use `record_checkpoint` for bounded resumable or terminal evidence and declared artifact or transient publication. Use the human-request or command-run operation only when it is exposed and the current task genuinely needs that external wait.

Use only the boundary outcomes exposed for the current role. Parent/root nodes use `yield` after staging one child; workers use `green`, `retry`, or `blocked`; root terminal release uses its separately validated outcome. After a successful boundary or external-wait opening, stop the current outer response immediately. The controller has already closed this dispatch; do not wait for provider completion, poll for a successor, or perform more work under the old dispatch.

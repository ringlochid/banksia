# Recover or replan a task

Inspect current task state, snapshot, waits, assignment, checkpoint, and artifacts before taking action.

Choose the smallest honest recovery:

- resolve a pending human request
- inspect or cancel the active command run
- retry when the assignment is still right
- replan when the workflow shape is wrong
- pause for operator intervention
- block when required facts, authority, tools, or external state are unavailable

Do not edit generated files to force recovery. Do not use `continue` as polling. Do not replan because one worker made a small recoverable mistake.

Workers may report shape problems. Root and parent nodes own structural replan and must adopt the smallest revision that restores an honest evidence path.

When the workflow shape is still right and a direct child has already finished, a live parent/root dispatch may use `assign_child` again to create a fresh bounded assignment for that child. This is legal only before a downstream artifact consumer has current work. The controller preserves the old assignment as history. If downstream work is already materialized, replan or start a new task rather than mixing old consumer evidence with a new producer assignment. A completed whole task is terminal and is not reopened by `continue`; start a new task when recovery is discovered only after whole-task closure.

Do not rewind a completed task or insert a late publication directly into controller history. To reuse a surviving workspace draft, start a new task against that workspace and identify the file as untrusted draft input to inspect, refine, and republish through the new assignment's declared artifact slot. The new task establishes fresh scope, checkpoint, review, and release authority.

See [task stuck or waiting](../help/task-stuck-or-waiting.md) for symptom-based help.

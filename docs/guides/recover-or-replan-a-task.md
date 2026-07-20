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

See [task stuck or waiting](../help/task-stuck-or-waiting.md) for symptom-based help.

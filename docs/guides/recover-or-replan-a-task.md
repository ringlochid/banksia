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

When the workflow shape is still right and a direct child has already finished, a Manager may include that available child in a new `delegate` call. This creates a fresh Assignment and a new controller-owned Wave; it never reopens or rewrites the earlier child result. Use a one-member Wave when later work depends on inspecting that return, and a multi-member Wave only for independent scopes. A completed whole Task is terminal and is not reopened by Resume; start a new Task when recovery is discovered only after whole-Task closure.

Do not rewind a completed Task or insert a late result directly into controller history. To reuse a surviving workspace draft, start a new Task against that workspace and include the loose file's path and purpose in the new Assignment. Treat its current bytes as input to inspect, not as controller-owned evidence. The new Task establishes fresh Assignment, Checkpoint, review, and Result authority.

See [task stuck or waiting](../help/task-stuck-or-waiting.md) for symptom-based help.

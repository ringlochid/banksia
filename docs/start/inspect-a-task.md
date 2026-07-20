# Inspect a task

Start with controller-owned state. Generated files help people and agents read that state, but they do not replace it.

## Use the console

Open `http://127.0.0.1:18125/` and select the task. The task page shows current state, the workflow graph, waits, controls, and event chronology.

## Use operator readbacks

The operator HTTP and MCP surfaces can read:

- current runtime task state
- operator snapshot and trace
- task events
- pending human requests
- command runs and logs

Use the [operator reference](../reference/operator/README.md) for exact tools and routes.

## Read task files

Find the data directory with:

```bash
autoclaw config show --json
```

Each task has a task root under `<data_dir>/tasks/<task_id>/`. Useful projections include:

- `_runtime/workflow-manifest.md`
- `_runtime/attempts/<attempt_id>/assignment.md`
- `_runtime/attempts/<attempt_id>/latest-checkpoint.md`
- `outputs/artifacts/`

The controller materializes these files after authoritative commits. Support files do not control provider start. The exact `instructions.md` and `input.md` pair referenced by a dispatch is different: it must exist before that dispatch can start. If a support file and a current controller readback disagree, trust the controller.

## Read events correctly

Task events explain chronology. They are not the current-state model. Read the task, snapshot, human-request, or command-run source row when you need current truth.

Next, read [inspect and control a task](../guides/inspect-and-control-a-task.md).

# Core concepts

AutoClaw separates reusable design, one launch request, live runtime state, and operator actions.

| Layer | Main objects | Purpose |
| --- | --- | --- |
| Authoring | role, policy, workflow | describe reusable behavior, authority, and work structure |
| Launch | task-compose | describe one concrete task and its path bindings |
| Runtime | task, flow, assignment, attempt, dispatch, checkpoint, artifact | record current work and durable evidence |
| Operation | snapshot, trace, human request, command run, controls | inspect and steer a live task |

## The five nouns to learn first

- **Workflow:** reusable node tree and evidence contract.
- **Task-compose:** one launch request that selects a workflow.
- **Assignment:** bounded mission for one active node.
- **Checkpoint:** recorded progress or handoff for one attempt.
- **Artifact:** durable output published into a declared slot.

## Node kinds

- `root` owns the whole task and final closure.
- `parent` routes work within a subtree.
- `worker` performs one bounded assignment.

The workflow tree determines the runtime node kind. Policies decide which tools, waits, and budgets each kind may use.

## Truth and projections

Controller database records are authoritative. Manifests, assignments, checkpoint files, artifact indexes, console views, and task events are projections or read models. They make the task understandable; they do not create legal state by themselves.

A provider saying it finished is also not task success. The task advances only through accepted controller transitions.

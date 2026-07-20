---
name: "autoclaw-work-orchestrator"
description: "Turn a 'use AutoClaw to do X' request into launched AutoClaw work: decide whether AutoClaw fits, pick or draft the right workflow, prepare task-compose, and launch or hand off. Use whenever the user asks to use AutoClaw to build, make, research, fix, plan, coordinate, or run something — that means launching AutoClaw-orchestrated work, not integrating AutoClaw into an app and not modifying AutoClaw source. Run autoclaw-task-interview first when scope, workflow shape, or roots paths are unconfirmed."
---

# autoclaw-work-orchestrator

Use this skill when the user asks you to use AutoClaw to coordinate, launch, or supervise a task.

This is the front door for AutoClaw usage. Keep it practical: choose whether to stay in chat/tools, reuse definitions, write definitions, draft task-compose, start a task, or hand off to runtime operation.

## Read The Request Correctly

"Use AutoClaw to build me an MVP" means launch an AutoClaw task that builds the MVP. It never means adding AutoClaw as a dependency of the user's app, wiring AutoClaw into a stack, or editing AutoClaw source code. Treat a request as integration or internals work only when the user says so explicitly ("integrate AutoClaw into my service", "fix this AutoClaw bug") — and then say you are leaving the AutoClaw usage lane. When the sentence genuinely supports two readings, ask one direct question before doing anything.

## Core Model

AutoClaw is useful when work benefits from durable roles, explicit evidence, checkpoints, artifacts, human decisions, long command runs, recovery, or auditable closure.

Memory model:

    Role = lens
    Policy = authority
    Node = mission
    Criteria = done gate
    Produces = evidence left behind
    Consumes = evidence required
    Workflow = evidence path
    Task-compose = one launch

## Intake Flow

1. Restate the requested job in one sentence.
2. Decide whether AutoClaw adds value. Stay local for small one-shot tasks.
3. For new or ambiguous work, run `autoclaw-task-interview` first: it confirms intent, scope, workflow shape, and `roots` path bindings, and produces the launch brief this skill executes.
4. Read only the current docs/reference needed for the decision, using `https://github.com/ringlochid/AutoClaw` as the public source or a matching local checkout.
5. Inspect current registry truth through operator MCP when choosing existing definitions.
6. Pick the smallest honest shape: reuse existing, adapt definitions, or draft new definitions.
7. Draft task-compose only after the workflow key and `roots` path bindings are confirmed, not guessed.
8. Ask before upload/import/apply/start unless the user clearly authorized that write.
9. After start, report the task id and stop; route later inspection/control to `autoclaw-runtime-operator` when the user asks.

## Verify, Do Not Assume

Before drafting or launching, check real state instead of relying on memory or plausible names:

- `workflow.key` must resolve in the current registry: confirm with `search_definitions` or `get_definition`, not from a remembered fixture list
- every host path in `roots` must be checked on disk before choosing `use_existing_host`; never invent a path, and never bind the user's repo without their confirmation
- role and policy keys referenced by new definitions must exist in current registry truth
- when a check fails, report the gap and ask; do not substitute a lookalike definition or path silently

## Reuse Or Write

Reuse an existing workflow when purpose, evidence path, capabilities, produced artifacts, and closure criteria match.

Write or adapt definitions when the task needs different roles, artifact handoffs, review gates, human decisions, command-run capability, incident posture, or closure evidence.

Do not create a new policy for every role. Use current standard policies unless node authority actually changes.

Current standard policy family:

- standard-root
- standard-root-human-request
- standard-parent
- standard-parent-human-request
- standard-worker
- standard-worker-human-request
- standard-worker-command-run

Base root/parent/worker policies are field-only.

## Shape Selection

Use fixed workflows when the path is known: bugfix, bounded feature implementation, release checklist, document generation, support classification, or predictable command sequence.

Use parent/root orchestration when the route depends on evidence: MVP build, ambiguous feature work, incident response, strategy, research, or multi-stage delivery.

Complexity is earned by uncertainty. Add parent routing, review loops, human checkpoints, or command-run lanes only when they improve evidence quality, recovery, or safety.

## Task-Compose Discipline

Task-compose owns one concrete launch:

- task.key
- task.title
- task.summary
- task.instruction
- workflow.key
- roots.workspace

Keep reusable doctrine in definitions, not task-compose. Put target paths, concrete constraints, accepted deferrals, and task-specific success conditions in task-compose.

Use current docs for exact `roots` binding modes. Use `ensure_task_default` for isolated task-owned paths and `ensure_host_path` for an explicit host path.

## Clarification Pass

`autoclaw-task-interview` owns the structured intake for new work. Use this pass only for residual questions that surface after the interview, or for small follow-up launches where a full interview is overkill.

Before asking the user, check docs, registry truth, shipped examples, task context, and obvious constraints.

Ask only when the answer changes workflow shape, the workspace binding, approval boundary, definition upload, or task start. Ask at most three concrete questions, with recommended options first.

Good decision points:

- draft only, upload definitions, or start now
- reuse an existing workflow or create a custom one
- task-owned paths or host-bound paths
- no human wait, human approval, human input, or human review
- inline commands or command-run-enabled worker lane

## Runtime Follow-Through

Default after start: confirm the task is running with one `get_runtime_task` readback, report the task id, task-compose path, and where results will land, then stop. Do not keep polling, watching, or resolving waits on your own — the user will ask for status or results later, and those reads belong to `autoclaw-runtime-operator`.

When the user asks for follow-up, or explicitly asked you to supervise the run:

- inspect through operator MCP, not hidden chat memory
- resolve human requests through the human-request surface
- inspect command runs through command-run surfaces
- treat support refs as diagnostics, not runtime truth

## Related Skills

- Use `autoclaw-task-interview` first for new or ambiguous work: intent, scope, workflow shape, and `roots` confirmation.
- Use `autoclaw-definition-author` for role/policy/workflow/task-compose YAML.
- Use `autoclaw-runtime-operator` after a task starts.

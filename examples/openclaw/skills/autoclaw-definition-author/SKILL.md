---
name: "autoclaw-definition-author"
description: "Write, revise, review, or explain AutoClaw roles, policies, workflows, task-compose files, and definition drafts. Use when the user asks for AutoClaw definition YAML or asks how an AutoClaw role, policy, workflow, node, criteria, or roots binding should be written. Not for developing AutoClaw internals; when the underlying scope or paths are unconfirmed, run autoclaw-task-interview first."
---

# autoclaw-definition-author

Use this skill when the user asks you to write, revise, review, or explain AutoClaw roles, policies, workflows, task-compose files, or definition drafts.

This is an AutoClaw usage skill. It is not for developing AutoClaw internals.

## Source Order

Use the public AutoClaw docs from `https://github.com/ringlochid/AutoClaw` as the stable source. When the agent is inside a matching checkout, local docs are equivalent and faster.

Read only the pages needed for the current definition:

1. `docs/guides/design-workflows-and-instructions.md`
2. `docs/guides/write-layered-instructions.md`
3. `docs/guides/write-a-role.md`
4. `docs/guides/write-a-policy.md`
5. `docs/guides/write-a-workflow.md`
6. `docs/guides/write-a-task-compose.md`
7. `docs/reference/definitions/**`
8. operator MCP registry reads when live controller truth matters

Treat shipped definitions as examples, not a closed menu.

## Core Model

A good AutoClaw definition is:

    purpose + evidence path + completion criteria

Layer split:

- role = reusable specialist lens
- policy = authority, budget, and capability guardrails
- workflow node = local mission
- criteria = hard done gate
- produces = durable evidence left behind
- consumes = required prior evidence
- workflow = reusable evidence path
- task-compose = one concrete launch

## Authoring Flow

1. State the job in one sentence. When scope, workflow shape, or `roots` paths are still unconfirmed, get them from `autoclaw-task-interview` instead of inventing them.
2. Identify closure evidence, non-goals, human decisions, long command needs, and `roots` path bindings.
3. Reuse current registry/seed definitions only when purpose, evidence path, capability gates, and closure match.
4. Write or adapt definitions when those differ.
5. Keep task-specific paths, constraints, deferrals, and launch instructions in task-compose.
6. Validate against current truth, not memory: resolve every referenced role and policy key with `search_definitions`/`get_definition`, check node-kind compatibility, policy presence, artifact slots, criteria slots, and confirm `roots` host paths exist on disk before `use_existing_host`.
7. Ask before upload/import/apply/start unless the user already authorized that write.

## Role Rules

Roles are durable specialist lenses. Keep them narrow, reusable, and evidence-oriented.

Good role instructions say what evidence to read first, what work mode to use, what output a parent/root can expect, and what not to widen.

Avoid generic roles such as assistant, helper, or worker.

## Policy Rules

Most work should use the current shipped policy family:

- standard-root
- standard-root-human-request
- standard-parent
- standard-parent-human-request
- standard-worker
- standard-worker-human-request
- standard-worker-command-run

Base standard-root, standard-parent, and standard-worker are field-only policies. Do not add policy instruction just because the role changed.

Write a new policy only when authority changes: node kind, retry or child-assignment budget, human-request permission/kinds, command-run permission, or a reusable prohibition. If the sentence describes the job, put it in a role or node instruction.

Budget rules:

- `retry_limit` is worker-only; it opens another attempt at the same assignment
- `child_assignment_limit` is root/parent-only; it bounds child assignments opened by one assignment
- one policy must not mix both budget fields
- omitted `budget_spec` means no controller budget counter for that family

Human requests and command runs are separate capabilities. Grant only the one the node needs. Long command work usually belongs on a worker with standard-worker-command-run or a deliberately narrow equivalent.

## Workflow Rules

Every workflow node should attach an explicit policy from current registry truth.

Use fixed workflows when the evidence path is known. Use explicit consumes, produces, and criteria for real handoffs.

Use parent/root orchestration when the route depends on evidence. Keep dynamic artifacts broad and stable, such as research_brief, risk_log, current_plan, evidence_bundle, or closure_report.

Every parent needs a routing job. Every worker needs one bounded mode. Criteria should be hard enough to block closure.

## Task-Compose Rules

Task-compose is one launch:

- task.key
- task.title
- task.summary
- task.instruction
- workflow.key
- roots.workspace

Do not put reusable doctrine in task-compose. Do not include secrets.

Prefer `ensure_task_default` for isolated first runs. Use `ensure_host_path` or `use_existing_host` for explicit host paths; see the current task-compose docs.

## Registry And Drafts

Controller registry truth wins after seed/upload/apply.

Operator MCP registry tools read current truth. `upload_definition` and `start_task` are writes and need authorization. Definition draft authoring stays on the trusted HTTP `/authoring` API.

## Related Skills

- Use `autoclaw-task-interview` when the scope, workflow shape, or workspace path behind a definition request is unconfirmed.
- Use `autoclaw-work-orchestrator` for use/reuse/write/start decisions.
- Use `autoclaw-runtime-operator` after a task starts.

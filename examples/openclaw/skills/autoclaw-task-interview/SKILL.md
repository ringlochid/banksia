---
name: "autoclaw-task-interview"
description: "Deep intake interview for new AutoClaw work: confirm intent, scope, workflow shape, and the workspace binding before anything is drafted or launched. Use FIRST whenever the user asks to use AutoClaw to build, make, research, fix, plan, or run something (for example 'use autoclaw to build an MVP for me') and the scope, workflow shape, or target directory is not already confirmed. Not for operating tasks that are already running, and not for integrating AutoClaw into an app or developing AutoClaw internals."
---

# autoclaw-task-interview

Use this skill before shaping or launching new AutoClaw work. Its output is a confirmed launch brief that `autoclaw-work-orchestrator` and `autoclaw-definition-author` can execute without guessing.

"Use AutoClaw to X" means: launch AutoClaw-orchestrated work that accomplishes X. It does not mean embedding AutoClaw in an application, wiring AutoClaw into a stack, or changing AutoClaw source code.

## Intent Gate

Classify the request before anything else:

| User says | Meaning | Route |
| --- | --- | --- |
| "use AutoClaw to build/make/research/fix/plan X" | launch AutoClaw work that does X | this interview, then `autoclaw-work-orchestrator` |
| "start a task", "have AutoClaw handle X" | launch AutoClaw work | this interview when scope or roots are unconfirmed |
| "why is task X waiting", "pause/continue/cancel task X" | operate an existing task | `autoclaw-runtime-operator`, no interview |
| "integrate AutoClaw into my app", "call the AutoClaw API from my service" | integration engineering on the user's product | ordinary engineering work; say explicitly that you are leaving the AutoClaw usage lane |
| "fix this AutoClaw bug", "change the AutoClaw controller" | AutoClaw internals development | ordinary development work, not these skills |

Default to the launch reading. Ask one direct question only when the sentence genuinely supports two readings. Never silently reinterpret a launch request as integration or internals work.

## Discover Before Asking

Interview questions are only for facts that live in the user's head. Everything else, check first with real reads:

- current registry truth: `search_definitions`, `get_definition`, `list_definition_versions`
- shipped workflow families: `docs/reference/definitions/workflows/**` in a checkout, or `https://github.com/ringlochid/AutoClaw`
- filesystem truth: list any directory the user mentioned; never assume a path exists or guess its layout
- conversation context: constraints and paths the user already stated

## Interview Areas

Cover all three areas. Skip a question when the answer is already confirmed evidence; never skip an area silently.

### 1. Scope

- the job in one sentence, in the user's words
- the concrete deliverable and where the user will look at it when done
- explicit non-goals and accepted deferrals
- constraints that would make a green closure dishonest (compatibility, privacy, budget, deadline)

### 2. Workflow shape

Propose a shape with a named candidate; do not ask open-endedly. Map the request to a shipped workflow family first, then verify the key against registry truth:

| Request smells like | Candidate family |
| --- | --- |
| build an MVP, prototype an idea | `mvp-build` |
| fix a bug end to end | `bugfix-review-release` |
| research a topic into a brief | `topic-research-brief` |
| bounded code change | `bounded-change` or `reviewed-change-release` |
| plan without building | `planning-only` |
| compare directions first | `idea-discovery` |

Then confirm the loop shape:

- fixed sequence when the evidence path is known; parent/root orchestration when the route depends on evidence
- human decision points: none, direction, approval, input, or review — and where they gate
- long command work (builds, test suites, deploys over ~2 minutes) that needs a command-run-enabled lane
- review gates strong enough to block weak output

### 3. Workspace binding

`roots.workspace` says where the task works. It is not the workflow `root` node. This binding decides whether AutoClaw touches real user files, so it is never guessable.

Confirm:

- task-owned isolated default (`ensure_task_default`), or a real host directory
- `ensure_host_path` when AutoClaw may create the host path, `use_existing_host` when it must already exist

Rules:

- never invent a host path
- verify every claimed host path with a real filesystem check before choosing `use_existing_host`; it fails at start when the path is missing
- default to `ensure_task_default` when the user has no target directory
- state the consequence in plain language: task-owned default keeps user files untouched; `use_existing_host` on a repo means the task edits that real directory

## Question Mechanics

- batch open questions into one round, at most five
- lead each question with a recommended option and say why
- use plain language; do not require the user to know AutoClaw nouns like boundary or criteria
- if the user says "just do it", choose safe defaults (isolated roots, human approval before external effects) and record them as assumptions in the launch brief

## Launch Brief

End the interview by restating a short brief and getting one confirmation:

- job sentence and deliverable
- workflow: reuse key, adapt, or new — and the loop shape
- workspace plan: mode plus verified path when using a host directory
- human decision points and command-run needs
- authorized writes: draft only, upload definitions, or start now

Follow-up mode is not an interview question: the default is to report the task id and stop once the task starts, with status and results read later when the user asks. Note active supervision in the brief only when the user explicitly requested it.

Then hand off: definition YAML to `autoclaw-definition-author`, launch mechanics to `autoclaw-work-orchestrator`, and later status or result reads to `autoclaw-runtime-operator`.

## Related Skills

- `autoclaw-work-orchestrator` executes the confirmed brief: reuse/write decision, task-compose, launch.
- `autoclaw-definition-author` writes any role, policy, workflow, or task-compose YAML the brief requires.
- `autoclaw-runtime-operator` takes over after the task starts.

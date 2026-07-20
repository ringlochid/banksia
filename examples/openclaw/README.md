# OpenClaw examples

Copyable material for the OpenClaw side of an AutoClaw install.

Canonical public source: <https://github.com/ringlochid/AutoClaw/tree/main/examples/openclaw>

- [`worker-workspace/AGENTS.md`](worker-workspace/AGENTS.md) — workspace instructions for the `autoclaw-worker` agent
- [`skills/autoclaw-task-interview/`](skills/autoclaw-task-interview/SKILL.md) — operator skill: intake interview that confirms intent, scope, workflow shape, and `roots` paths before new work is shaped or launched
- [`skills/autoclaw-work-orchestrator/`](skills/autoclaw-work-orchestrator/SKILL.md) — operator skill: shape a request into AutoClaw work and launch it
- [`skills/autoclaw-runtime-operator/`](skills/autoclaw-runtime-operator/SKILL.md) — operator skill: inspect, resolve waits, control, and recover running tasks
- [`skills/autoclaw-definition-author/`](skills/autoclaw-definition-author/SKILL.md) — operator skill: write roles, policies, workflows, and task-compose files

Install steps and the annotated OpenClaw config block are in [Set up OpenClaw agents and operator skills](../../docs/guides/set-up-openclaw-agents-and-skills.md).

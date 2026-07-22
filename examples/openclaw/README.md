# OpenClaw examples

Copyable material for the OpenClaw side of a Banksia install.

Canonical public source: <https://github.com/ringlochid/banksia/tree/main/examples/openclaw>

- [`worker-workspace/AGENTS.md`](worker-workspace/AGENTS.md) — workspace instructions for the `banksia-worker` agent
- [`skills/banksia-task-interview/`](skills/banksia-task-interview/SKILL.md) — operator skill: intake interview that confirms intent, scope, workflow shape, and `roots` paths before new work is shaped or launched
- [`skills/banksia-work-orchestrator/`](skills/banksia-work-orchestrator/SKILL.md) — operator skill: shape a request into Banksia work and launch it
- [`skills/banksia-runtime-operator/`](skills/banksia-runtime-operator/SKILL.md) — operator skill: inspect, resolve waits, control, and recover running tasks
- [`skills/banksia-definition-author/`](skills/banksia-definition-author/SKILL.md) — operator skill: write roles, policies, workflows, and task-compose files

Install steps and the annotated OpenClaw config block are in [Set up OpenClaw agents and operator skills](../../docs/guides/set-up-openclaw-agents-and-skills.md).

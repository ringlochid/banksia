# Product overview

AutoClaw is a local-first controller for multi-step AI work. It turns reusable definitions and one launch request into a task that can be inspected, resumed, reviewed, and recovered.

Use it when work needs more than one unstructured agent turn:

- bounded delegation
- durable checkpoints and artifacts
- explicit review and release rules
- human decisions or long command waits
- retry, replan, and operator recovery

AutoClaw is not a provider transcript, prompt library, or generic shell runner. Providers run agent loops. AutoClaw owns the task, current assignment, legal state changes, and evidence needed to finish.

The shortest path is:

```text
definitions + task-compose -> controller task -> provider dispatch -> MCP transition -> next controller state
```

Read [core concepts](core-concepts.md) for the small vocabulary behind this path.

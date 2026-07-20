# How-to guides

Status: Target

These pages are operator-facing and target-system usage guides for the design surface.

Use live design terms here:

- `consumes / produces / criteria`, not `inputs/outputs.handoffs`
- `assignment`, `latest checkpoint`, and durable artifacts, not `result record`
- `continuity-state` and provider session recovery, not generic `binding`
- controller/DB truth first, with `_runtime/dispatch/*` files used as observability projections during debugging

## Start here

- [Install and onboard](install-and-onboard.md)
- [Run local SQLite](run-local-sqlite.md)
- [Use Postgres](use-postgres.md)
- [Write a nested workflow](write-a-nested-workflow.md)
- [Debug a stalled node](debug-a-stalled-node.md)
- [Recover a provider session](recover-a-provider-session.md)
- [Publish a release](publish-a-release.md)

Implementation-program notes and review records are local execution material, not tracked target usage guidance.

## Search-first routing

If you are asking:

- "How do I onboard or boot the design locally?" -> [Install and onboard](install-and-onboard.md)
- "How do I define a nested workflow with current schema terms?" -> [Write a nested workflow](write-a-nested-workflow.md)
- "How do I debug a stuck assignment or stalled execution?" -> [Debug a stalled node](debug-a-stalled-node.md)
- "How do I recover provider continuity without redefining assignment truth?" -> [Recover a provider session](recover-a-provider-session.md)
- "How do I move from how-to into worked examples?" -> [Tutorials](../tutorials/README.md)

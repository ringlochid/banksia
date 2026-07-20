# Design a workflow

Design the evidence path before writing YAML. A workflow should make it clear what must happen, what each node may do, and what evidence can close the task.

## Start with five questions

1. What outcome does the user need?
2. What evidence proves that outcome?
3. Which work needs an independent review?
4. Which decisions need a human?
5. Which failures need retry, replan, or blocked closure?

## Choose the smallest useful shape

| Shape | Use it when |
| --- | --- |
| Single worker | one bounded output and proof loop are enough |
| Root, worker, reviewer | work needs one independent quality gate |
| Fixed sequence | each stage depends on a named earlier artifact |
| Routing parent | evidence decides which child should run next |
| Command-run worker | long command work needs logs, a deadline, or cancellation |

Split work only when the handoff improves authority, evidence, or recovery. One worker can often inspect context, implement a bounded change, and run focused tests.

## Give each layer one job

- Role: reusable specialist lens.
- Policy: authority, capabilities, and budgets.
- Node: mission in this workflow.
- Criteria: hard done gate.
- Produces: durable output.
- Consumes: required earlier evidence.
- Task-compose: one launch request.

## Design evidence before agents

List the artifacts and criteria the root needs at closure. Then add only the nodes needed to produce and review them. Fixed workflows should use precise `consumes` and `produces`; dynamic workflows should keep a few stable evidence slots and let a parent route from current results.

## Check real tools

Confirm the selected provider can use the required file, shell, browser, document, or service tools. Provider-native tools are separate from AutoClaw node capabilities. Long commands belong in a command-run-enabled worker; human judgment belongs in a human-request-enabled node.

## Pilot before scaling

Run one small task. Inspect its assignment, checkpoint, artifacts, snapshot, trace, and real tool use. Expand the workflow only after the evidence path is clear.

Next, [write layered instructions](write-layered-instructions.md) or use the [definition examples](../reference/definitions/README.md).

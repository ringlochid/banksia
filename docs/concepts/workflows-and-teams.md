# Workflows and teams

A Banksia Workflow is a reusable team of responsibilities. It answers **who is responsible**. The Task lead decides **what should happen next**, and the controller records **what actually happened**.

That separation is the central design rule. A Workflow is not a pipeline, a schedule, or a list of authored steps.

## Workflow identity and revisions

A Workflow has a stable ID and one mutable draft at most. Publishing a valid draft creates an immutable numbered Workflow revision and removes the draft. Later edits happen in another draft and produce another immutable revision.

Starting a Task pins one published revision. The complete responsibility tree is materialized as that Task's initial team before provider work starts. A later publication under the same Workflow ID cannot change a running Task.

This gives each layer one job:

- the Workflow ID identifies the reusable team;
- a published revision preserves the exact authored definition selected at Task start;
- the Task-local team records the exact responsibilities in force during that run; and
- Assignments, Waves, waits, and Checkpoints record the temporal choices made for that Task.

## One recursive team shape

Every Workflow has one lead. A Member may have children, and every child uses the same recursive Member shape:

```text
lead
├── delivery-manager
│   ├── implementation-owner
│   └── test-owner
└── independent-reviewer
```

The positions have concrete meanings:

- **lead:** the root Member. The lead owns the complete Task and the exact Result returned to the user.
- **Manager:** any current Member with direct children. A Manager keeps its complete Assignment, decides how to use its children, assesses their Checkpoints and referenced files, and integrates the result.
- **Contributor:** a Member with no direct children. A Contributor performs the substantive work in its Assignment directly.

A Member can become a Manager or Contributor after a runtime replan because behavior follows the current direct-team shape.

## Responsibility is not time

`children` records direct responsibility and accountability. Array order is organizational; it does not prescribe execution order.

Using the team above, the delivery Manager might:

- delegate implementation first and testing second when the test depends on the implementation;
- place credibly independent code and test work in one parallel Wave;
- ask the implementation owner to repair concrete review findings, then ask the reviewer to inspect the repaired state;
- give one reusable owner several item-specific Assignments for a bounded maintenance batch; or
- combine sequence, parallel work, review loops, and batches.

Those are runtime decisions. The same published revision can use a different pattern for a different Task.

A Wave always belongs to one immediate Manager and may contain one or more current direct children. A one-member Wave is the normal durable path for dependent sequence; multiple members provide bounded parallel fan-out. Nested Managers own their own local Waves and joins.

Participation is stricter than joining one Wave. Before a Manager can return `green`, every current direct child configuration must have an accepted green return on its current branch basis. A blocked return settles its Wave position but does not satisfy participation; a retry settles neither. A Manager that intends to take over substantive execution must remove every direct child first and continue under fresh Contributor context.

Iteration and batch work also reuse ordinary Assignments. Review feedback is new meaning and therefore becomes a fresh feedback-bearing Assignment. Repeating the exact immutable Assignment after an execution problem is the narrower retry case. A Workflow does not author loop counts, item lists, or a batch mode.

## A team must add value

A Manager must add decomposition, evidence assessment, integration, or a decision. This is a quality failure:

```text
parent repeats its Assignment to one child
child reports a Checkpoint
parent repeats that Checkpoint as its own result
```

That relay adds coordination without accountability. Give the substantive work to the right Member, or give the Manager genuinely distinct responsibility. Do not add filler children merely to make a one-Member Workflow look like a team.

A one-Member Workflow is valid and often better when:

- the work is tightly coupled;
- the same files would require constant coordination;
- no independent review or specialization would improve the result; or
- the job is small enough that delegation would only add ceremony.

## Team-specific prose

The top-level `description` is the nonblank catalog explanation of when to use the Workflow. The optional top-level `note` is shared Markdown for this team's specific boundaries, collaboration preferences, caveats, or non-goals.

Each Member may add:

- a `title` for display;
- a `description` for responsibility and routing;
- an `instruction` for reusable, Member-specific contribution guidance; and
- optional advanced provider and capability settings.

Only the Member `id` is required. Blank, whitespace-only, or explicit `null` values for optional prose normalize to omission. Sparse definitions are valid because every runtime Assignment still carries a complete, nonblank work request.

Notes and instructions should not restate general Banksia operation rules. Delegation, waits, Checkpoints, replanning, file handoffs, Human Requests, and Command Runs are taught by the controller-owned system prompt and enforced by runtime legality.

## Replanning one subtree

A current Manager may change only descendants in its own subtree:

- `add_child` adds one new direct child and may include a recursively new subtree;
- `update_child` patches one existing descendant and may update or add listed descendants; and
- `remove_child` explicitly removes one descendant subtree from future team revisions.

Replanning never changes an existing Member ID, reparents a Member, or reorders siblings. Omission never means deletion. Busy affected subtrees are protected, and history remains unchanged.

An accepted replan creates a fresh Task-local team revision. The provider turn that requested it stops. After the organization manifest is current, a fresh same-Attempt continuation receives the updated team and legal actions. Work outside the caller's subtree remains unchanged.

## Start simple; disclose control progressively

Fresh installations include seven provider-neutral, capability-neutral Starters:

| Starter | Use it for |
| --- | --- |
| `reviewed-code-change` | Implement, independently review, repair, and recheck one bounded change. |
| `debug-and-verify` | Reproduce a difficult defect, challenge causes, repair, and verify independently. |
| `cross-layer-feature` | Coordinate a shared contract, disjoint layers, and end-to-end verification. |
| `bounded-maintenance-batch` | Process a finite inventory with item ownership and completeness review. |
| `evidence-synthesis` | Gather local and current evidence, challenge it, and own one supported conclusion. |
| `technical-decision` | Compare options under local constraints and make an accountable choice. |
| `reproducible-study` | Separate methods, execution, replication, and claim audit. |

Starters omit `provider` and `capabilities` throughout the tree. Provider selection resolves from controller configuration, while Human Request and Command Run remain denied until a user grants them narrowly in a customized draft.

The three maintained [advanced reference Workflows](../../examples/workflows/README.md) demonstrate deliberate provider, sandbox, network, and capability choices. They are importable examples, not installed Starters.

See [Author a Workflow](../guides/author-a-workflow.md) for the publication journey and the [Workflow definition reference](../reference/workflows/README.md) for exact fields and validation.

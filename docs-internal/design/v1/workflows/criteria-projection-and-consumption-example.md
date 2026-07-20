# Criteria projection and consumption example

Status: Target

This page is the canonical end-to-end explanation of staged delivery criteria semantics under the parent-first verification model.

It expands the staged delivery release example without changing the frozen target behavior.

## Declaration inventory

| Source owner        | Kind     | Slot                                 | Purpose                                              |
| ------------------- | -------- | ------------------------------------ | ---------------------------------------------------- |
| root                | criteria | `root_delivery_rules`                | delivery and escalation rules before green or replan |
| root                | criteria | `root_closure_criteria`              | final root closure requirements                      |
| discovery           | criteria | `discovery_requirements`             | shared discovery requirements for the subtree        |
| delivery_loop       | criteria | `delivery_loop_requirements`         | shared delivery requirements for the subtree         |
| delivery_loop       | criteria | `delivery_review_criteria`           | review-step verification criteria                    |
| implement_change    | criteria | `implement_change_delivery_criteria` | engineering delivery criteria                        |

## Projection map

- direct-parent criteria project downward only when authored through `child_defaults.criteria`
- workers consume projected criteria refs from their direct parent plus any local criteria or explicit authored `consumes.criteria`
- review worker consumes the current owning subtree evidence and configured review criteria refs through ordinary child execution
- ordinary release work consumes surfaced release evidence through authored `consumes.artifacts` plus configured root-owned closure criteria refs

## Discovery subtree

`gather_evidence` is a worker leaf under `discovery`.

It sees:

- the direct-parent projected `discovery_requirements`
- no hidden ancestor criteria beyond what the direct parent explicitly projects

It does not invent new acceptance criteria at runtime.

### Concrete discovery view

If `gather_evidence` is the current worker, its assignment should surface:

- `summary`
- `instruction`
- `criteria` refs for `discovery_requirements`
- any authored `consumes`
- optional curated docs surfaced through explicit durable refs

It should not receive hidden ancestor bundles, invisible scope summaries, or criteria projected from beyond its direct parent.

## Delivery subtree

`delivery_loop` is a parent node with local criteria and ordinary review work.

The delivery subtree semantics are:

- `delivery_loop_requirements` defines the shared subtree acceptance contract
- `child_defaults.criteria` projects that slot onto direct children
- `plan_delivery` and `implement_change` therefore see both the projected subtree requirements and their own local delivery criteria
- `review_change` sees the projected subtree requirements plus the explicitly consumed `delivery_review_criteria`
- `implement_change` still depends on authored hard inputs such as `discovery_brief` and `delivery_plan`; criteria projection does not replace typed-input legality

## Review child

When `delivery_loop` reaches review:

- `review_change` is an ordinary authored child node
- it consumes the current subtree evidence and the configured `delivery_review_criteria`
- parent verification still decides whether the subtree may release `green`

## Root release work

Root release work is bounded:

- it consumes only the surfaced release evidence declared through authored `consumes.artifacts`
- it consumes only the selected root-owned `root_closure_criteria`
- it does not reopen planning or implementation scope

Example surfaced release evidence for `release_closure`:

- `discovery_brief`
- `delivery_plan`
- `change_patch`
- `verification_report`
- `review_report`
- `qa_report`

## Attempt pinning rule

Attempts pin exact criteria refs they consumed.

That means:

- `gather_evidence` pins the refs behind its active delivery criteria
- `gather_evidence` therefore pins `discovery_requirements`
- implementation children pin the projected subtree criteria plus any local criteria they consumed
- `review_change` pins the same subtree criteria plus the review-step criteria refs
- `release_closure` pins the surfaced release artifact refs and the root-closure criteria refs

## Parent verification consequence

Parent verification is controller-assembled over:

- current direct-child outputs
- current ordinary review outputs when present
- current consumed criteria refs
- current subtree evidence

Parent or root does not treat a criteria slot as satisfied merely because it was declared. The current evidence must support it.

## Related contracts

- [Staged delivery release example](examples/staged-delivery-release.md)
- [Criteria and parent verification](criteria-and-parent-verification.md)
- [Workflow schema appendix](workflow-schema-appendix.md)
- [Review findings contract](review-findings-contract.md)

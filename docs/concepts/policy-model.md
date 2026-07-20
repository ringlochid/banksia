# Policy model

A policy describes reusable node authority. It should not describe a job title or one task.

## Write a new policy only when authority changes

Authority includes:

- compatible node kinds through `applies_to`
- retry or child-assignment budget
- allowed human-request kinds
- command-run permission
- reusable prohibitions or capability rules

If only the work changes, keep the policy and change the role or node instruction.

## Budget rules

- `retry_limit` belongs to worker policies.
- `child_assignment_limit` belongs to root or parent policies.
- Do not mix both counters in one policy.
- An omitted `budget_spec` means no controller counter for that family.

## Capability defaults

Omitted human-request and command-run capability is denied. Grant only the capability the node needs. A human request is for judgment; a command run is for controller-managed long command work.

Use the packaged standard policies when they fit. See [write a policy](../guides/write-a-policy.md) for YAML and [capability model](capability-model.md) for behavior.

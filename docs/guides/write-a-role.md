# Write a role

A role is one reusable specialist lens. Name the real responsibility, such as `scope_reviewer` or `bug_fix_engineer`, rather than `helper` or `worker`.

```yaml
kind: role
id: scope_reviewer
title: Scope Reviewer
description: Reviews one bounded scope for contradictions, feasibility, and risk.
allowed_node_kinds:
    - worker
instruction: >-
  Read the accepted purpose, scope, criteria, and evidence before judging the proposal. Do not implement. Publish a clear decision, required corrections, and residual risks.
```

Use `parent` or `root` only for a role whose durable job is routing or closure. Keep task paths, secrets, one-off requests, budgets, and tool grants out of roles.

Check that the role says what evidence to read, what output to leave, what not to widen, and which uncertainty to surface.

See the [role examples](../reference/definitions/roles/README.md).

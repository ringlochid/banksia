# Write a policy

A policy grants reusable controller authority. Start from a packaged standard policy and create another only when authority changes.

```yaml
kind: policy
id: bounded_worker
title: Bounded Worker
description: Worker authority with one retry and no external waits.
applies_to:
    - worker
budget_spec:
    retry_limit: 1
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: deny
```

Rules:

- `retry_limit` is for workers.
- `child_assignment_limit` is for roots and parents.
- Do not mix both budget families.
- Omitted capability is denied.
- Omitted budget means no controller counter for that family.

Grant human requests only for `direction`, `approval`, `input`, or `review` decisions. Grant command runs only for long controller-managed command work. Use policy instructions only when the fields need an extra capability rule.

See the [policy examples](../reference/definitions/policies/README.md).

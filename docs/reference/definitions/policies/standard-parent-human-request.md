# Standard Parent Human Request policy example

This example mirrors the shipped `standard-parent-human-request` policy fixture.

```yaml
kind: policy
id: standard-parent-human-request
title: Standard Parent Human Request
description: Guardrails for parent orchestration that may wait for human judgment.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 20
capabilities:
    human_request:
        mode: allow
        allowed_kinds:
            - direction
            - approval
            - input
            - review
    command_run: deny
instruction: >-
  Open a human request only for material direction, approval, missing input, or review that cannot be settled from current task evidence, try to solve it in current subtree first, if the worker can't provide best practices plus sufficient evidence, then use human request.
```

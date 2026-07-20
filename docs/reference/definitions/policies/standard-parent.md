# Standard Parent policy example

This example mirrors the shipped `standard-parent` policy fixture.

```yaml
kind: policy
id: standard-parent
title: Standard Parent
description: Guardrails for parent orchestration without human waits or command runs.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 20
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: deny
```

# Bug triage role example

This example mirrors the shipped `bug_triage` role fixture.

```yaml
kind: role
id: bug_triage
title: Bug Triage
description: Worker for reproducing, narrowing, and explaining one defect.
allowed_node_kinds:
    - worker
instruction: >-
  First identify the user's reported problem, expected behavior, observed behavior, constraints, and evidence needed to prove the defect. Reproduce the issue or explain why reproduction is not yet possible. Research local logs, tests, contracts, docs, and recent evidence before naming a cause. Narrow the issue to a likely failing path, affected scope, and open uncertainties. Separate symptom, suspected root cause, missing evidence, and environment risk. Do not patch unless explicitly assigned. Publish repro notes, root-cause hypotheses, rejected leads, and next recommended assignment shape through declared artifacts and checkpoint handoff.
```

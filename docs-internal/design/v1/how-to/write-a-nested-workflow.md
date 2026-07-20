# Write a nested workflow

Status: Reference

This page describes how to author the target nested workflow shape.

## Procedure

1. Define the root parent node.
2. Add child nodes explicitly under `children`.
3. Declare authored dependency edges with `consumes` and explicit acceptance constraints with `criteria`.
4. Declare produced durable outputs with `produces`.
5. Keep criteria ownership explicit through ordinary parent/root, worker, and review-child structure rather than gate subtypes.
6. Keep parent/root coordination and worker/review execution explicit through ordinary node roles and the current runtime model, not through implied callback or handoff families.

## Use these owner pages

- [Workflow definition schema](../workflows/workflow-definition-schema.md)
- [Typed dependency selectors and produce slots](../workflows/typed-dependency-selectors-and-produce-slots.md)
- [Criteria and parent verification](../workflows/criteria-and-parent-verification.md)
- [Task compose schema](../workflows/task-compose-schema.md)

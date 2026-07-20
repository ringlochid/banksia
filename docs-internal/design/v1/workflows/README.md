# Design workflows

Status: Target

This surface owns authored workflow schema, task-compose launch input, dependency selectors, criteria, parent/root review and release behavior, local runtime structural replan, and exemplar workflow material.

## Search-first routing

If you are asking:

- "What is the authored workflow schema?" -> [Workflow definition schema](workflow-definition-schema.md)
- "What is the launch-task-compose schema?" -> [Task compose schema](task-compose-schema.md)
- "What is the exact compiler validate-preview and launch materialization workflow?" -> [Compiler contract and launch materialization](compiler-contract-and-launch-materialization.md)
- "What replaces old typed inputs and output slots?" -> [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md)
- "How do criteria and parent verification work?" -> [Criteria and parent verification](criteria-and-parent-verification.md)
- "How does a parent inspect worker output before release?" -> [Parent worker review model](parent-worker-review-model.md) and [Criteria projection and consumption example](criteria-projection-and-consumption-example.md)
- "How do parent/root release and closure work?" -> [Parent/root release and closure](parent-root-release-and-closure.md)
- "How does runtime local replan work?" -> [Runtime structural replan](runtime-structural-replan.md)
- "Where is exhaustive authored-shape, patch, and example coverage?" -> [Workflow schema appendix](workflow-schema-appendix.md)
- "What replaces current `skill_refs`?" -> [Workflow definition schema](workflow-definition-schema.md), [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md), and [Plugin tool reference](../interfaces/plugin-tool-reference.md)
- "Which example should I read?" -> [Bounded change example](examples/bounded-change.md), [Reviewed change release example](examples/reviewed-change-release.md), or [Staged delivery release example](examples/staged-delivery-release.md)

## Start here

- [Workflow definition schema](workflow-definition-schema.md)
- [Workflow schema appendix](workflow-schema-appendix.md)
- [Task compose schema](task-compose-schema.md)
- [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md)
- [Criteria and parent verification](criteria-and-parent-verification.md)
- [Parent review and replan](parent-review-and-replan.md)
- [Parent worker review model](parent-worker-review-model.md)
- [Criteria projection and consumption example](criteria-projection-and-consumption-example.md)
- [Parent/root release and closure](parent-root-release-and-closure.md)
- [Runtime structural replan](runtime-structural-replan.md)
- [Bounded change example](examples/bounded-change.md) for the smallest teaching subgraph
- [Reviewed change release example](examples/reviewed-change-release.md) for the smallest workflow with ordinary release work
- [Staged delivery release example](examples/staged-delivery-release.md) for the richest staged reference flow

## Supplemental orientation

- [Provider direction and provider-native capabilities](provider-direction-and-provider-native-capabilities.md)
- [Parent/root planning surface](parent-root-planning-surface.md)

## Keywords

- workflow schema
- task-compose schema
- typed dependency selectors
- produce slots
- criteria
- parent verification
- parent/root release
- runtime structural replan
- workflow examples
- skill refs removal

## Surface rule

Use this surface for target workflow authoring, dependency, criteria, ordinary review or release work, runtime structural replan, and exemplar contracts.

Use ADRs for durable rationale. Do not recreate deleted archive or execution trees for live owner routing.

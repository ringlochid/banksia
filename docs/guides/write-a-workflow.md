# Write a workflow

A workflow is a reusable node tree and evidence contract.

## Build from closure backward

1. State the user outcome in one sentence.
2. Name the artifacts and criteria that prove it.
3. Add the smallest nodes that can produce and review that evidence.
4. Assign each node one role, one compatible policy, a bounded mission, and explicit inputs and outputs.
5. Add human or command waits only where required.

Use a fixed chain when the evidence order is known. Use a routing parent when current evidence must choose the next child. Every parent needs a real routing job; every worker needs one bounded assignment.

## Make criteria enforceable

Good criteria can reject the result: the patch fixes the reproduced defect, the required verification passed, and unresolved high-risk regressions block release. Wording such as "do a good job" belongs in instruction, not criteria.

## Route failure honestly

- Retry for another attempt at the same assignment.
- Replan when the node tree or dependencies are wrong.
- Ask a human when judgment is missing and policy allows it.
- Block when required external state remains unavailable.

Publish with the console authoring workbench or:

```bash
autoclaw definitions import --file ./workflow.yaml
```

Use `--overwrite allow_new_revision` only when you intend to publish changed content as a new current revision. See the [workflow examples](../reference/definitions/workflows/README.md) for exact YAML.

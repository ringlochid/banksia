# Workflow examples

These advanced definitions are maintained authoring and review references:

- [`advanced-cross-layer-delivery.yaml`](advanced-cross-layer-delivery.yaml) —
  a deeper service-and-experience team whose shared contract, layer ownership,
  integration, and provider access stay explicit.
- [`advanced-reviewed-code-change.yaml`](advanced-reviewed-code-change.yaml) —
  a code-change team with write-capable implementation, read-only review,
  focused proof, Human Request grants, and managed Command Run access.
- [`advanced-technical-decision.yaml`](advanced-technical-decision.yaml) — a
  source-backed decision team separating local inspection, externally managed
  upstream research, counterargument, and independent review.

These are reference examples, not controller seeds. They demonstrate optional
provider, sandbox, network, Human Request, and Command Run configuration that
may not fit every installation. Banksia separately bootstraps seven portable
Starter Workflows without provider or capability choices.

Import an advanced example explicitly when its access choices match your
installation:

```bash
banksia workflow import --file \
  examples/workflows/advanced-reviewed-code-change.yaml
```

YAML is convenient in an editor. The Console and HTTP API use the same model as
JSON. A definition describes stable responsibilities, not a scheduled list of
steps. The running lead decides how the team should work from the Task and
current evidence.

Task inputs and file references remain separate from the reusable Workflow:

```json
{
  "workflow": "advanced-technical-decision",
  "prompt": "Compare the two migration approaches and recommend one.",
  "files": [
    {
      "path": "docs/migration-constraints.md",
      "description": "Constraints accepted by the project"
    }
  ]
}
```

The file entry is a loose path plus an optional short description. It does not
create an additional controller resource.

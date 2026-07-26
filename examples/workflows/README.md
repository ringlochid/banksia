# Workflow examples

These definitions are maintained references for authoring and review:

- [`minimal.yaml`](minimal.yaml) — the smallest valid one-member team.
- [`full.yaml`](full.yaml) — a complete delivery team with nested members, provider settings, Human Requests, and Command Runs.
- [`omx-autopilot.yaml`](omx-autopilot.yaml) — a deep product-delivery team adapted from the OMX Autopilot responsibility pattern.
- [`omx-best-practice-research.yaml`](omx-best-practice-research.yaml) — a research team separating repository facts, upstream evidence, criticism, and synthesis.

These are reference examples, not controller seeds. A packaged installation owns its provider-neutral starter Workflows separately. Import an example explicitly when you want to use it:

```bash
banksia workflow import --file examples/workflows/minimal.yaml
```

YAML is convenient in an editor. The Console and HTTP API use the same model as JSON. The definition describes responsibilities rather than a scheduled list of steps; the running lead decides which members should work sequentially, in parallel, iteratively, in batches, or with a hybrid plan.

Task inputs and file references are intentionally separate from the reusable Workflow. For example:

```json
{
  "workflow": "omx-best-practice-research",
  "prompt": "Compare the two migration approaches and recommend one.",
  "files": [
    {
      "path": "docs/migration-constraints.md",
      "description": "Constraints accepted by the project"
    }
  ]
}
```

The file entry is a loose path plus an optional short description. It does not create an additional controller resource.

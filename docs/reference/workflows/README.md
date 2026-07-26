# Workflow definition reference

The maintained JSON Schema is [`workflow-definition.schema.yaml`](workflow-definition.schema.yaml). It validates the common JSON-compatible model accepted from both YAML and JSON.

## Top-level fields

| Field | Required | Meaning |
| --- | --- | --- |
| `kind` | yes | Closed discriminator; always `workflow`. |
| `id` | yes | Stable Workflow identity. |
| `description` | yes | Nonblank catalog explanation of when to use the Workflow. |
| `note` | no | Shared team-specific Markdown guidance. |
| `lead` | yes | Top Member, using the same shape as every descendant. |

## Member fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable tree-wide unique Member identity. |
| `title` | no | Display title. |
| `description` | no | Responsibility and routing hint. |
| `instruction` | no | Reusable team-specific contribution guidance. |
| `provider` | no | Codex, Claude, or OpenClaw selection. |
| `capabilities` | no | Narrow Human Request and Command Run grants. |
| `children` | no | Ordered direct responsibilities using this same Member shape. |

Optional title, description, instruction, and note values accept `null`, an empty string, or whitespace at ingestion and normalize them to omission. The top-level Workflow description must remain nonblank.

## `$defs` and `$ref`

`$defs` is a section inside the schema where reusable validation shapes are named. `$ref` points to one of those shapes. For example, the schema defines `workflowMember` once under `$defs`, then the lead and every child refer back to it. That is how one finite schema describes a tree of any depth without copying the Member rules repeatedly.

Workflow authors do not write `$defs` or `$ref` in their YAML or JSON. Those keywords belong only to the validation schema.

## Provider variants

`provider.kind` selects the provider-specific shape:

- `codex` and `claude` may include `model`, `effort`, and `sandbox`;
- `openclaw` accepts no additional Workflow provider fields; and
- omission resolves the controller default at Task start.

`kind` is used because it discriminates one provider configuration variant from another. A Member has a provider selection; the selected variant's kind is Codex, Claude, or OpenClaw.

Network is configured only inside a managed provider's `sandbox`. There is no standalone `network_access` field.

## Validation layers

JSON Schema validates document shape, bounds, and closed fields. Banksia ingestion also normalizes optional prose and validates semantic invariants such as tree-wide unique Member IDs and supported provider settings.

Use the maintained [reference examples](../../../examples/workflows/README.md) as authoring fixtures. They are not packaged starter Workflows.

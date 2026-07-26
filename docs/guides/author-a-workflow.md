# Author a Workflow

Use YAML in a text editor or JSON through the Console and HTTP API. Both formats parse into the same closed Workflow model.

## Start small

The smallest valid definition is:

```yaml
kind: workflow
id: one-member-work
description: Complete a task with one accountable lead.
lead:
    id: lead
```

The Workflow description is required and appears in selection surfaces. A Member needs only a stable `id`; add prose when it makes responsibility or routing clearer.

## Add responsibilities

Use `children` to describe the lead's direct team:

```yaml
kind: workflow
id: reviewed-change
description: Implement a bounded change and review it independently.
note: |
    Keep implementation and review independent. Return consequential findings
    for no more than two focused repair passes.
lead:
    id: delivery-lead
    title: Delivery lead
    instruction: >-
      Reconcile the change, proof, and independent review.
    children:
        - id: implementer
          title: Implementer
          instruction: >-
            Implement the requested change and focused proof.
        - id: reviewer
          title: Independent reviewer
          instruction: >-
            Review the integrated change without editing it.
```

Do not encode a sequence in array order or restate general orchestration rules in every instruction. The running Manager receives the full Assignment and chooses the execution pattern from current evidence.

## Configure only what differs

Omit `provider` to use the controller default. Add a provider block only when the Workflow requires a specific route or managed execution setting:

```yaml
provider:
    kind: codex
    model: gpt-5.6
    effort: high
    sandbox:
        mode: workspace_write
        network: deny
```

Codex and Claude support model, effort, and sandbox settings. OpenClaw accepts only `kind: openclaw`.

Capabilities deny by default. Grant only the operation the Member may need:

```yaml
capabilities:
    human_request:
        - direction
        - approval
    command_run: allow
```

## Validate and import

The maintained schema is [`docs/reference/workflows/workflow-definition.schema.yaml`](../reference/workflows/workflow-definition.schema.yaml). It covers document shape; Banksia ingestion also enforces semantic rules such as tree-wide Member ID uniqueness.

Import a YAML or JSON file as a controller-owned draft:

```bash
banksia workflow import --file ./reviewed-change.yaml
```

Import from standard input with an explicit format:

```bash
banksia workflow import --file - --format json < reviewed-change.json
```

If a draft already exists, repeat the import with its current opaque ETag:

```bash
banksia workflow import --file ./reviewed-change.yaml --etag '<current-etag>'
```

Import does not publish. Review, validate, and publish the draft in the Console, through the Operator, or with the HTTP draft endpoints. Task start selects only published revisions.

## Export a published revision

Write the current published revision to a file:

```bash
banksia workflow export reviewed-change --output ./reviewed-change.yaml
```

Standard output requires an explicit format:

```bash
banksia workflow export reviewed-change --format json
```

See the maintained [examples](../../examples/workflows/README.md) for advanced teams with explicit provider, sandbox, network, and capability choices.

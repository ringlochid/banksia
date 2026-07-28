# Workflow definition reference

The machine-readable public contract is [`workflow-definition.schema.yaml`](workflow-definition.schema.yaml). It is JSON Schema Draft 2020-12 and validates the common JSON-compatible model accepted from JSON and YAML.

## Complete shape

```yaml
kind: workflow
id: reviewed-change-custom
description: Implement, review, and recheck one bounded code change.
note: >-
  Preserve reviewer independence and route accepted findings back to the
  implementation owner.
lead:
  id: change-lead
  title: Change lead
  description: Owns scope, integration, finding disposition, and Result.
  provider:
    kind: codex
    model: gpt-5.6
    effort: high
    sandbox:
      mode: workspace_write
      network: deny
  capabilities:
    human_request:
      - direction
      - review
  children:
    - id: implementation-owner
      instruction: >-
        Own the bounded production change and focused proof.
      capabilities:
        command_run: allow
    - id: independent-reviewer
      instruction: >-
        Inspect the integrated state without editing it.
      provider:
        kind: claude
        sandbox:
          mode: read_only
          network: deny
```

This hierarchy defines responsibility. It does not require the lead to run children in array order or in parallel.

## Top-level fields

| Field | Required | Contract |
| --- | --- | --- |
| `kind` | yes | Closed discriminator; exactly `workflow`. |
| `id` | yes | Stable Workflow identity. |
| `description` | yes | Nonblank catalog explanation of when the Workflow is useful; maximum 1,024 characters. |
| `note` | no | Shared team-specific Markdown; maximum 8,192 characters. |
| `lead` | yes | Root Member using the same recursive shape as every descendant. |

No additional top-level properties are accepted.

## Recursive Member fields

| Field | Required | Contract |
| --- | --- | --- |
| `id` | yes | Stable Member identity, unique across the complete tree. |
| `title` | no | Display title. |
| `description` | no | Responsibility and routing hint. |
| `instruction` | no | Reusable team-specific contribution guidance. |
| `provider` | no | One discriminated Codex, Claude, or OpenClaw selection. |
| `capabilities` | no | Narrow Human Request and Command Run grants. |
| `children` | no | Ordered direct responsibilities, each using this same Member shape. |

Optional Member prose is bounded to 16,384 characters per field. Member array order is organizational, not temporal. A Member may have at most 32 direct children; semantic ingestion accepts at most 256 Members and a Member-tree depth of 12.

The schema uses `$defs.workflowMember` and recursive `$ref` values to express this shape. Workflow authors do not put `$defs` or `$ref` in their documents.

## IDs

Workflow and Member IDs:

- contain 1 to 128 characters;
- begin with a lowercase ASCII letter;
- continue with lowercase letters and digits, with groups optionally separated by one `-` or `_`; and
- match `^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$`.

Member IDs must be unique across the complete tree. Publication revisions, Task IDs, and controller-issued runtime identities are separate concepts; do not encode a revision or runtime version into the authored Workflow ID.

## Optional prose normalization

At ingestion, these values normalize to omission when they are `null`, empty, or whitespace-only:

- top-level `note`; and
- Member `title`, `description`, and `instruction`.

Line endings normalize to `\n`. The top-level `description` remains required and nonblank.

This normalization does **not** apply to structural or control fields. Explicit `null` is rejected for `provider`, `capabilities`, and `children`. An empty `capabilities` object is invalid because it grants nothing; omit the field instead. An omitted `children` field or an empty array means the Member is a leaf in a complete authored Workflow.

## Provider discriminator and settings

`provider.kind` selects one closed variant:

### Codex

```yaml
provider:
  kind: codex
  model: gpt-5.6
  effort: high
  sandbox:
    mode: workspace_write
    network: deny
```

Allowed Codex effort values are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`.

### Claude

```yaml
provider:
  kind: claude
  model: claude-sonnet-4-5
  effort: high
  sandbox:
    mode: read_only
    network: deny
```

Allowed Claude effort values are `low`, `medium`, `high`, `xhigh`, and `max`.

Codex and Claude accept optional exact `model`, `effort`, and `sandbox`. Portable sandbox pairs are:

| `mode` | `network` |
| --- | --- |
| `read_only` | `deny` |
| `workspace_write` | `deny` or `allow` |
| `full_access` | `allow` |

Network is nested inside `sandbox`; there is no standalone Workflow network field. When the authored sandbox block is omitted, managed-provider resolution forms a `full_access` plus `allow` request. The configured `[runtime]` sandbox pair is a controller ceiling, not the omitted authored request: it may narrow either the default request or an explicit authored request, but it never widens one. Each Dispatch records the requested and effective pairs, and the managed provider receives the effective pair.

### OpenClaw

```yaml
provider:
  kind: openclaw
```

OpenClaw accepts no Workflow-authored model, effort, sandbox, Gateway, or network fields. Those properties remain user-operated outside the Workflow.

When `provider` is omitted, Task start resolves the controller's configured default. Provider settings do not inherit from a parent Member.

## Default-deny capabilities

The only authored capability grants are:

```yaml
capabilities:
  human_request:
    - input
    - direction
    - approval
    - review
  command_run: allow
```

`human_request` must contain one to four unique kinds from the closed list above. `command_run` has the one literal grant value `allow`.

Omission denies the operation. Grants do not inherit from parent Members. Controller or deployment policy may narrow or revoke a grant at Dispatch time but never widen the authored request.

## Parsing and validation

The shipped ingestion path:

1. accepts one UTF-8 JSON object or one nonempty YAML document, up to 1 MiB;
2. rejects duplicate keys, YAML anchors, aliases, merge keys, unsupported explicit tags, nonstring object keys, nonfinite numbers, illegal text characters, and non-JSON-compatible values;
3. normalizes optional prose and line endings;
4. validates the closed schema and provider variants; and
5. validates semantic invariants such as tree-wide Member-ID uniqueness, capability-kind uniqueness, and Member count/depth bounds.

Validation reports issue source, document path, and message. A valid preview does not publish or start work. Publishing requires the exact current draft ETag and creates a new immutable numbered revision.

Each Workflow may have at most one active mutable draft. Draft mutations, discard, undo, and publish use currentness checks. Undo receipts are single use. A Task can start only from a published revision and pins that exact revision for its lifetime.

## Starters and maintained references

Fresh/reset controller state contains exactly these installed Starters:

- `decision-through-competing-prototypes`;
- `deep-research-and-decision-brief`;
- `experiment-and-replication-program`;
- `idea-to-validated-demo`;
- `incident-investigation-and-recovery`;
- `migration-and-modernisation`;
- `production-feature-delivery`; and
- `security-audit-and-hardening`.

They omit `provider` recursively so they remain portable across configured installations. A Starter may grant a supported Human Request kind or managed Command Run to the exact Member whose responsibility needs it. Omitted grants remain denied and never inherit.

The maintained [advanced reference Workflows](../../../examples/workflows/README.md) are:

- `advanced-cross-layer-delivery`;
- `advanced-reviewed-code-change`; and
- `advanced-technical-decision`.

They demonstrate meaningful provider, sandbox, network, and capability choices. They are importable JSON/YAML authoring examples, not packaged Starters.

## Deliberately absent

The Workflow contract has no:

- Role, Policy, or Skill definition system;
- external MCP server, resource, prompt, elicitation, or plugin field;
- authored steps, phases, edges, modes, loops, or schedules;
- `criteria`, `consume`, `produce`, expected-output, or task-array fields; or
- managed Artifact identity, version, hash, approval, or lifecycle.

Use [Workflows and teams](../../concepts/workflows-and-teams.md) for the mental model and [Configuration](../configuration.md) for controller defaults.

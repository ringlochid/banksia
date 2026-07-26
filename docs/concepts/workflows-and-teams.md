# Workflows and teams

A Banksia Workflow is a reusable responsibility tree. It says who should own each part of a kind of work; it does not prescribe a fixed sequence of steps.

## One recursive shape

Every definition has:

- `kind: workflow`;
- a stable Workflow `id`;
- a required, nonblank catalog `description`;
- an optional shared `note`; and
- one `lead`.

The lead and every descendant use the same Member shape:

```yaml
id: member-id
title: Optional display title
description: Optional routing hint
instruction: >-
  Optional team-specific contribution guidance
provider:
    kind: codex
capabilities:
    command_run: allow
children: []
```

Only `id` is required on a Member. `title`, `description`, `instruction`, `provider`, `capabilities`, and `children` may be omitted. Blank or whitespace-only optional prose and explicit `null` normalize to omission. A sparse Member is still meaningful because every runtime Assignment carries a complete required prompt.

Member IDs are stable and unique across the complete tree. They are human-readable identities, not hashes or runtime versions.

## Responsibility is not schedule

`children` records direct responsibility relationships. Array order is organizational, not execution order. At runtime, a Manager can choose the pattern that best fits the current Assignment:

- sequence work when one result informs the next;
- delegate independent work in one parallel Wave;
- repeat a review-and-repair cycle;
- process a large repetitive scope in bounded batches; or
- combine these patterns.

A Member with current direct children behaves as a Manager: it keeps the complete Assignment, delegates complete child Assignments, and integrates their Checkpoints. A Member without children behaves as a Contributor and performs the substantive work directly. Runtime replan operations can add, update, or remove descendants inside the current Manager's subtree; existing Member IDs never change.

## Shared note and member instructions

The top-level `note` is optional Markdown for guidance specific to this team: collaboration preferences, purpose, caveats, or non-goals. It is projected into the Task directory when present.

A Member `instruction` specializes that Member's reusable responsibility or independent lens. Neither field should restate Banksia's general rules. Delegation, waits, Checkpoints, file handoffs, replanning, Human Requests, and Command Runs are taught by the system prompt and enforced by the controller.

## Provider settings

Omitting `provider` resolves the controller's configured default provider. Providers do not inherit from a parent Member.

Managed Codex and Claude selections can request:

- an exact provider-native `model`;
- an adapter-supported `effort`; and
- a portable `sandbox` pairing.

The supported sandbox pairs are:

| Mode | Network |
| --- | --- |
| `read_only` | `deny` |
| `workspace_write` | `allow` or `deny` |
| `full_access` | `allow` |

When the block is omitted, the current managed-provider default is `full_access` with network allowed. Deployment policy may narrow an authored request.

OpenClaw accepts only `provider: {kind: openclaw}`. OpenClaw remains a user-operated provider transport; Banksia does not author its model, sandbox, or Gateway configuration inside a Workflow.

## Capabilities

Human Request and Command Run are the only authored capability grants:

```yaml
capabilities:
    human_request:
        - input
        - direction
        - approval
        - review
    command_run: allow
```

Each omitted capability is denied. Grants do not inherit. Controller or deployment policy may narrow a grant but never widen it.

External MCP servers, Skills, arbitrary tools, fixed steps, completion criteria, declared inputs or outputs, and standalone network settings are intentionally outside the current Workflow contract.

See [Author a Workflow](../guides/author-a-workflow.md) and the [schema reference](../reference/workflows/README.md).

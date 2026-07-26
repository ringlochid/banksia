# Workflows and teams

A Banksia Workflow is a reusable responsibility tree. It says who should own each part of a kind of work; it does not prescribe a fixed sequence of steps.

## Starter teams

Fresh installations include seven provider-neutral, capability-neutral Workflows. Each turns a familiar loose subagent practice into explicit responsibility and review boundaries:

| Workflow | Use it for | Accountability upgrade |
| --- | --- | --- |
| `reviewed-code-change` | A bounded implementation, review, and repair | Separates production and proof ownership from independent review; the lead owns finding disposition. |
| `debug-and-verify` | An intermittent or poorly understood defect | Keeps reproduction, competing hypotheses, cause-based repair, and independent verification distinct. |
| `cross-layer-feature` | A feature spanning a shared contract and multiple layers | Gives the contract and each layer a clear owner, then verifies the integrated user outcome. |
| `bounded-maintenance-batch` | A finite migration, cleanup, or repetitive repair | Establishes a complete inventory, bounded item ownership, systematic review, and repository-wide verification. |
| `evidence-synthesis` | A question requiring local and external evidence | Separates workspace facts, authoritative sources, criticism, and lead-owned synthesis. |
| `technical-decision` | A consequential choice under real local constraints | Compares advocacy and counterargument against the same criteria and records revisit conditions. |
| `reproducible-study` | A computational, data, benchmark, or empirical study | Separates method, execution, independent replication, and claim audit. |

The maintained [advanced examples](../../examples/workflows/README.md) add deliberate provider, sandbox, network, Human Request, and Command Run choices. They are importable references, not installed Starters.

## From loose subagents to a Banksia team

### Developer: implement, review, and repair

In a loose subagent conversation, a developer often asks one agent to change code and another to review it. The primary agent may forward the original prompt unchanged, accept a green summary without inspecting the patch, or repeat review text as its own answer. If rework is needed, the distinction between another execution attempt and a new assignment with new meaning is easily lost.

With `reviewed-code-change`, the developer starts one Task with the exact change, compatibility boundary, and relevant file references. The change lead owns the complete outcome. Its implementation manager gives the code owner and test owner distinct work, inspects their Checkpoints and current files, and integrates the production and proof changes. The independent reviewer receives the integrated scope, records ranked findings in a loose file such as `.banksia/t_<id>/artifacts/change-review.md`, and links that path from its Checkpoint. A fix-now finding becomes a fresh, feedback-bearing Assignment; it is not disguised as a runtime retry. The change lead returns one verified result that explains accepted fixes and residual risk instead of relaying a child summary.

The Workflow does not author that order. On one Task, the lead may sequence implementation before review because review depends on the patch. On another, it may first delegate independent read-only compatibility research in parallel. The controller records the actual Assignments, Waves, waits, and Checkpoints chosen for that Task.

### Researcher: gather, challenge, and synthesize

In a loose research workflow, a researcher may ask several subagents to search, inspect local material, and critique an answer. Their outputs often arrive as disconnected summaries whose provenance and disagreements disappear when the primary agent concatenates them.

With `evidence-synthesis`, the Task prompt defines the exact question and decision boundary. The local evidence researcher links workspace observations and exact locations; the source researcher records authoritative sources, dates, versions, and applicability; and the evidence critic reviews consequential claims, missing counterexamples, and overreach. Members can preserve a shared question boundary in `.banksia/t_<id>/notes/` and put reviewable evidence tables or analysis under `.banksia/t_<id>/artifacts/`, then pass only a path and short description in Assignments or Checkpoints. These are ordinary shared files, not controller-owned Artifact objects.

The research lead decides which contributions can run in parallel and which criticism needs a prior evidence return. It inspects the referenced files, resolves or exposes contradiction, labels inference, and writes one conclusion with confidence and limitations proportionate to the evidence. The responsibility tree remains reusable even when a later question needs a different sequence, an extra review loop, or a bounded follow-up Assignment.

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

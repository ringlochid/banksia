# Workflow node schema

Status: Target

This page defines the V2 portable authored schema for workflow-node fields.

## Core rule

Workflow nodes own portable authored execution intent.

They do not own:

- machine-local provider config
- host paths
- auth material
- adapter session ids
- transport details

Those stay in `config.toml`, runtime, or adapter-owned local state.

This page owns the portable node object even while the outer workflow-definition envelope may evolve.

## `WorkflowNodeInput`

V2 authored workflow nodes use a portable body such as:

```yaml
node_key: string
kind: root | parent | worker
title: string | optional
role_id: string
policy_id: string
provider:
    kind: codex | claude | openclaw
description: string
instruction: >-
  string | optional
```

Field meaning:

- `node_key` is the stable logical node identity inside the workflow definition
- `kind` is the structural execution kind
- `title` is optional authored display metadata
- `role_id` points to the portable role definition the node should resolve at launch or adopt time
- `policy_id` points to the portable policy definition the node should resolve at launch or adopt time
- `provider` is an optional strict portable selection object whose `kind` chooses one logical provider
- `description` is reusable node-purpose text and remains distinct from guidance layers
- `instruction` is optional node-local prompt guidance for how this node should execute its role

## Validation rules

Validation must enforce:

- `node_key`, `kind`, `role_id`, `policy_id`, and `description` are required
- `kind` accepts only `root`, `parent`, or `worker`
- `provider`, when present, is discriminated by `kind` and accepts only `codex`, `claude`, or `openclaw`
- each current-phase provider variant contains only `kind`; unknown and provider-inapplicable fields fail validation
- `provider` is optional and omission means runtime resolves through the machine-local configured default
- `instruction`, when present, is non-empty prompt guidance authored on the node itself
- runtime and projection fields disambiguate this source as `node_instruction`, separate from `role_instruction`, `policy_instruction`, task instruction, and assignment instruction

## Separation rule

`provider` is reusable authored intent only.

Rules:

- `provider` belongs on workflow nodes, not role or policy definitions
- `provider` is not a model/effort block, Gateway profile, socket path, auth ref, sandbox config, or transport block
- machine-local config decides how this host reaches `openclaw`, `codex`, or `claude`
- provider-specific machine settings are resolved into the committed dispatch route rather than authored node fields
- controller truth records requested and resolved provider provenance without turning local config into authored definition truth
- active flow nodes and immutable node-plan revisions preserve this optional authored kind so structural adoption and later dispatch opening resolve the same intent

Structural `add_child` accepts the same optional strict provider object on every drafted node. Structural `update_child` distinguishes omission from explicit `null`: omission preserves the current provider selection, a provider object replaces it, and `null` returns the node to configured-default resolution. Adopted revisions preserve that exact authored choice.

## Non-goals

This page does not define:

- the full outer workflow-definition container shape
- machine-local provider setup
- machine-local default and no-fallback resolution semantics
- provider-specific MCP tool names

## Related contracts

- [Role and policy definition schema](role-and-policy-definition-schema.md)
- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
- [Provider CLI and check](provider-cli-and-check.md)
- [Node and Operator MCP surface contract](node-and-operator-mcp-surface-contract.md)

# Prompt layer (v2)

Status: Target

This folder owns the V2 provider-neutral two-file dispatch request and role-specific operating policy.

## Core model

- every committed dispatch references exactly `instructions.md` and `input.md`;
- the exact files are published before D2+refs commit and never rerendered by provider start;
- instructions and dynamic input remain separate through every adapter;
- dynamic input renders full controller IDs, assignment/attempt context, trigger, refs, capabilities, and continuation truth;
- prompts teach only the logical Node tools exposed to the dispatch role;
- managed Codex/Claude tools use semantic-only schemas through a private binding;
- experimental OpenClaw tools use the same catalog with explicit full task/dispatch selectors;
- work plans are optional assignment-owned guidance rather than a provider-session requirement;
- checkpoints remain durable handoff or terminal evidence; and
- provider configuration, output, terminal state, and hidden transcript memory never become request truth.

## Start here

1. [Prompt system](prompt-system.md)
2. [Generated contract readback](generated/contract-readback.md)
3. [Work plan and checkpoint contract](../architecture/work-plan-and-checkpoint-contract.md)
4. [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
5. [Node and Operator MCP surface](../interfaces/node-and-operator-mcp-surface-contract.md)
6. [V1 prompt-layer front door](../../v1/prompt-layer/README.md) for baseline and migration contrast

## Ownership boundary

The prompt owner defines assembly, role assets, dynamic input, publication invariants, tool teaching, and conformance. Runtime owners define dispatch legality, plans, checkpoints, waits, files, bindings, and boundaries. Adapters deliver the committed request without changing its semantic contract.

Current prompt assets and code remain shipped-behavior evidence until V2 implementation replaces them. V2 does not add separate prompt preview, diff, hash-gating, or provider-resume products.

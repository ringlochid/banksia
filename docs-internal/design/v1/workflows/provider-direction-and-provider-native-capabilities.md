# Provider direction and provider-native capabilities

Status: Target

This page owns the v1 rule for provider-facing capability direction and the removal of generic `skill_refs`.

## Canonical v1 rule

V1 does not encode provider selection or provider capability routing in:

- authored workflow schema
- manifests
- assignments, checkpoints, or artifacts
- ordinary worker context
- operator-safe public/plugin parity contracts

That means:

- no authored provider-selection fields
- no generic `skill_refs`
- no provider capability lists in worker-facing prompts
- no parent planning over provider names or provider-specific capability inventories

## What still exists

Provider-native detail may still exist in adapter implementation surfaces such as transport wrappers, continuity pointers, watchdog behavior, or internal adapter tooling.

Those details do not redefine:

- assignment meaning
- checkpoint meaning
- artifact publication
- role/policy schema
- controller-owned runtime truth or currentness

## Related canonical owners

- authored workflow surface -> [Workflow definition schema](workflow-definition-schema.md)
- prompt teaching surface -> [Prompt contract](../prompt-layer/contract.md)
- worker runtime surface -> [Worker context contract](../architecture/worker-context-contract.md)
- adapter-safe parity surface -> [Plugin tool reference](../interfaces/plugin-tool-reference.md)
- transport-specific continuity behavior -> [OpenClaw session lifecycle](../architecture/openclaw-session-lifecycle.md) and [OpenClaw continuity and send modes](../architecture/openclaw-continuity-and-send-modes.md)

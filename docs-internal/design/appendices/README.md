# Banksia design appendices

Status: Reference

These appendices provide exact fixtures, baseline traceability, and bounded implementation-reference protocols for the versionless Banksia design. The eight subject pages at the [design front door](../README.md) own normative product behavior; an appendix does not create a parallel contract.

## Workflow fixtures

- [Workflow JSON Schema](workflow-definition.schema.yaml) is the one authored schema serialized as YAML. Strict JSON and YAML inputs normalize to this same JSON-compatible value.
- [Maintained Workflow examples](workflow-examples/README.md) are readable documentation and validation fixtures. They may demonstrate optional provider and capability fields and are never installed automatically.
- [Packaged Starter Workflow fixtures](workflow-seeds/README.md) are the separate, provider-neutral bootstrap inputs intended for implementation in the Workflow package. They recursively omit provider and capability fields.

## Migration and implementation references

- [Baseline and removal ledger](baseline-and-removal-ledger.md) maps each preserved controller invariant to current ownership, direct proof, and its later replacement package. It also records characterized baseline failures that WP-00 must not misrepresent as new regressions.
- [n8n reference protocol](n8n-reference-protocol.md) records the pinned upstream source-study boundary, sparse packets, provenance rules, and the evidence required from every UI or UI-facing backend delegation. No n8n source or screenshot is tracked here.
- [Operator conversation and effect contract](operator-conversation-contract.md) freezes the exact routes, durable records, provider isolation, confirmations, and crash-recovery boundary for the separate Operator agent.

## Prompt readback owner

The generated [Task-member prompt contract readback](generated/task-member-prompt-contract-readback.md) belongs under this versionless appendix tree. The [system-prompt owner](../system-prompts.md) remains normative; the generated page is a deterministic readback of the shipped Banksia prompt assets and composition contract, not a second source of authority.

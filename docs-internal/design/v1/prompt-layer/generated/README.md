# Generated Prompt Artifacts

Status: Reference

This folder contains generated or generator-owned prompt-layer search aids and secondary machine artifacts.

Generated prompt artifacts in this folder derive from app-owned prompt assets under `apps/api/src/autoclaw/runtime/prompt/assets/` plus live prompt-render output from `render_prompt_bundle()`. They do not reverse-own the shipped runtime source. The shipped asset source remains byte-exact, and the prompt-pack docs mirror those bytes rather than normalizing their whitespace.

Read this folder only after the live owner docs:

- [Contract](../contract.md)
- [Source And Sections](../source-and-sections.md)
- [Field Renderers](../field-renderers.md)
- [Machine Contract](../machine-contract.md)
- [Runtime Rule Blocks](../prompt-pack/runtime-rule-blocks.md)
- [System And Provider Block](../prompt-pack/system-and-provider-block.md)
- [Validation And Reject Blocks](../prompt-pack/validation-and-reject-blocks.md)

Keep this mental model in mind while reading generated artifacts:

- the generated files echo controller-first runtime truth; they do not replace it
- manifest, assignment, checkpoint, and `consumed_durable_refs` stay separate on purpose
- `_runtime/dispatch/` remains observability only, even when generated examples mention it
- prompt artifact persistence is handled by synchronous task-root writers after commit; these generated examples describe the prompt body, not the persistence timing
- same-attempt parent/root continuity is shown through ordinary `full_prompt` examples with session-key reuse, not through a second continuation-wrapper family
- if a generated artifact appears to teach missing paths, guessed rules, or stale semantics, the owner docs win and the artifact is stale

## What Lives Here

- [../prompt-catalog.yaml](../prompt-catalog.yaml) generated machine-readable family, exact-block, example, and validation-route catalog
- [Inventory](inventory.md) generated section, family, send-mode, block, and example inventory
- [Rendered Examples](rendered-examples.md) generated or canonicalized rendered examples

This folder does not define a third dispatch prompt family for validation or reject messages. It also does not overrule the prompt-catalog distinction between `live_instruction_block` exact blocks and `reference_only` exact blocks.

Validation and reject semantics that the generated prompt artifacts may route to still live in the current owner docs outside this folder:

- [Validation And Reject Blocks](../prompt-pack/validation-and-reject-blocks.md)
- [Runtime Boundary And Controller Loop Contract](../../architecture/runtime-boundary-and-controller-loop-contract.md)
- [API Schema Appendix](../../interfaces/api-schema-appendix.md)

The API schema appendix carries the `operation_failure` wire fields. Prompt-layer wording still belongs to the prompt-pack and runtime-boundary owner docs.

## Authority Rule

If generated artifacts drift from the live owner docs:

1. the live owner docs win
2. `prompt-catalog.yaml` and generated files are stale
3. those secondary artifacts must be regenerated

If generated artifacts start teaching:

- a third canonical prompt family
- `instruction_text`
- `writable_roots`
- `url` or `uri` surfaced refs
- `version_label`
- gate-era boundary families
- full artifact current-pointer internals

they are stale and must be regenerated.

## Search-First Routing

- "What is the current section order?" [Inventory](inventory.md)
- "Which exact system block is canonical?" [System And Provider Block](../prompt-pack/system-and-provider-block.md)
- "Which exact runtime legality block is canonical?" [Runtime Rule Blocks](../prompt-pack/runtime-rule-blocks.md)
- "What should a worker prompt look like?" [Rendered Examples](rendered-examples.md)
- "What should a parent/root prompt look like?" [Rendered Examples](rendered-examples.md)
- "How do generated examples show same-attempt parent/root reuse?" [Rendered Examples](rendered-examples.md)
- "Where is the generated example registry?" [Inventory](inventory.md)
- "Where is the exact prompt-layer reject wording page?" [Validation And Reject Blocks](../prompt-pack/validation-and-reject-blocks.md)
- "Where are the exact `operation_failure` carrier fields?" [API Schema Appendix](../../interfaces/api-schema-appendix.md)
- "Where is `boundary_precondition_failed` defined exactly?" [Runtime Boundary And Controller Loop Contract](../../architecture/runtime-boundary-and-controller-loop-contract.md)

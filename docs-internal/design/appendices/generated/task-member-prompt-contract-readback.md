# Shipped AutoClaw Task-member prompt baseline readback

Status: Reference

This page is generated from the shipped AutoClaw 0.1.8 prompt contracts and five instruction assets. It is deterministic migration-baseline evidence, not Banksia target prompt truth. The versionless [Task-member system-prompt contract](../../system-prompts.md) is normative; WP-05 replaces these inputs and regenerates this same versionless readback. Run `make docs-prompt-generate` after changing an input, then run `make docs-prompt-check`.

## Instruction assets

- instructions/shared/authority.md
- instructions/shared/context-access.md
- instructions/shared/control-transfer.md
- instructions/families/worker.md
- instructions/families/parent-root.md

## Family composition

- worker: instructions/shared/authority.md, instructions/shared/context-access.md, instructions/shared/control-transfer.md, instructions/families/worker.md
- parent_root: instructions/shared/authority.md, instructions/shared/context-access.md, instructions/shared/control-transfer.md, instructions/families/parent-root.md

## Dynamic input

`assignment | trigger | plan | context | dispatch | next`

## Trigger kinds

`root_start | accepted_boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue | structural_replan`

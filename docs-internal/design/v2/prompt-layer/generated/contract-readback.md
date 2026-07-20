# V2 prompt contract readback

Status: Reference

This page is generated from the shipped V2 prompt contracts and five instruction assets. Run `make docs-prompt-generate` after changing either input, then run `make docs-prompt-check`.

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

`root_start | accepted_boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue`

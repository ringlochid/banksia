# AutoClaw extended standards

Status: Reference

This directory holds long-form agent guidance that supports the [root agent contract](../../AGENTS.md) and the [repo coding standard](../../STYLE.md) without turning those root files into books.

## Precedence

- the [root agent contract](../../AGENTS.md) wins on repo policy, routing, verification, and delegation
- the [repo coding standard](../../STYLE.md) wins on measurable coding standards and refactor triggers
- the owning design/current pages win on surface-specific target and shipped-behavior truth
- files in this directory explain how to apply those rules in larger structural or cleanup work

## Use order

Read only the smallest relevant subset:

1. the [root agent contract](../../AGENTS.md)
2. the [repo coding standard](../../STYLE.md)
3. the relevant design/current owner page
4. the relevant file in this directory

If a future subtree `AGENTS.md` exists near the code you are touching, read it after the root files and before applying the matching standard.

## Structure

- [standards writing guide](./standards-writing.md): how the standards stack itself should be structured and maintained
- [code standards](./code/): code-writing and symbol-level standards
- [structure standards](./structure/): repo, source, integration, and test layout standards
- [docs standards](./docs/): docs information architecture standards

## File map

### Code
- [readability and refactor standard](./code/readability-refactor.md)
- [naming standard](./code/naming.md)

### Structure
- [repo layout standard](./structure/repo-layout.md)
- [source layout standard](./structure/source-layout.md)
- [test structure standard](./structure/test-structure.md)
- [integration boundary standard](./structure/integration-boundaries.md)

### Docs
- [Docs structure guide](./docs/docs-structure.md)

## Update rule

Update these files when the root rules stay stable but the repo needs better examples, sharper cleanup guidance, or a clearer operating playbook.

If a change alters measurable repo-wide policy, update the [root agent contract](../../AGENTS.md) or the [repo coding standard](../../STYLE.md) instead of hiding the rule here.

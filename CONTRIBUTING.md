# Contributing to Banksia

Banksia is in active development. Contributions should strengthen one explicit product or engineering contract without creating parallel truth, compatibility paths, or unrelated cleanup.

## Read the owners first

Before changing tracked files:

1. Read the root [agent contract](AGENTS.md) for repository policy, mandatory owner routing, delegation, and applicable proof.
2. Read the root [coding standard](STYLE.md) for measurable implementation and refactor rules.
3. Start at the [internal documentation router](docs-internal/README.md), then read the smallest owner for the surface you will change.
4. Use the [maintainer verification guide](docs/maintainers/README.md) to select the shipped proof lane.
5. Read only the relevant extended guide under [`.agents/standards/`](.agents/standards/README.md) when the root contracts need more detail.

Do not treat code shape, tests, ignored research, or generated output as permission to override an owning product contract. If the owner is silent and the answer would change product behavior, stop and raise the exact gap before implementing it.

## Prepare a source checkout

The PyPI package is the normal user installation. Contributors should work from a clean repository checkout:

```bash
git clone https://github.com/ringlochid/banksia.git
cd banksia
make backend-install
make console-install
```

Use `./.venv/bin/banksia ...` for source-checkout CLI commands. To run the bundled local Console through `./.venv/bin/banksia serve`, prepare its ignored assets first:

```bash
make console-package-assets
```

For active frontend work, use `make console-dev` instead. The exact Python and Node.js requirements live in [`pyproject.toml`](pyproject.toml) and [`console/package.json`](console/package.json).

## Work in a bounded slice

- Identify the owning contract, shipped surface, consumers, and meaningful failure before editing.
- Preserve unrelated work in the shared worktree.
- Start with the smallest focused test or validator that can expose the gap.
- Keep docs, implementation, generated contracts, and behavior proof together when the change crosses them.
- Use the shipped DB, runtime, CLI, API, browser, package, or reset path when the claim belongs to that boundary; mocks and test-only setup are not equivalent proof.

The root contracts own detailed code style and test placement. Do not duplicate those rules in a pull request or invent a local substitute.

## Run applicable proof

Iterate with focused commands, then run every final gate required by `AGENTS.md` for the touched surface. Common aggregators are:

```bash
make check-backend
make test-backend
make test-backend-integration
make check-console
make check-docs
```

These commands are not interchangeable. `make check-backend` does not run tests, and database, end-to-end, browser, package, provider, or reset changes require their separately owned lanes. Use [maintainer verification](docs/maintainers/README.md) for the exact matrix and record any skipped command with its concrete blocker and affected claim.

Before handoff, inspect the complete diff, run `git diff --check`, and report:

- the owning contract and intended outcome;
- changed files and public behavior;
- exact commands and results;
- any skipped lane, residual risk, or follow-up owner; and
- whether generated, package, schema, service, or reset proof was applicable.

For a product decision that is not already owned, open an [issue](https://github.com/ringlochid/banksia/issues) with the observed gap and constraints rather than encoding a guess in code.

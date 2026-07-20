# Choose a verification lane

Use this guide to decide which checks prove a change. Start from the surface changed, then add deeper lanes only when the change reaches that behavior.

`make check-api` is not a test command. It runs lint, mypy, and pyright.

## Quick selection

| Changed surface                                                                         | Minimum verification                                                                                         |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| public docs only                                                                        | `make check-docs`, plus a stale-term scan after moves or deletions                                            |
| internal docs only                                                                      | `make check-docs`                                                                                            |
| docs scripts                                                                            | docs script focused tests when present, `ruff check scripts/docs`, `mypy scripts/docs`                       |
| prompt assets or prompt catalog                                                         | prompt catalog generate when inputs changed, prompt catalog validate, focused prompt rendering tests         |
| role, policy, workflow, or task-compose examples                                        | definition schema/catalog focused tests, `make docs-contract-check`, reference link scan                     |
| Python backend logic                                                                    | focused pytest while iterating, `make check-api`, applicable unit/integration lanes                          |
| CLI setup, config, OpenClaw, service, or package behavior                               | CLI focused tests, install/start reference checks, `make check-api`, package or service smoke when practical |
| runtime, registry, DB, or task launch behavior                                          | focused tests, `make check-api`, `make test-api-unit`, `make test-api-integration`                           |
| Postgres, schema, reset, upgrade, or cross-DB behavior                                  | all SQLite-relevant checks plus `make test-api-db`                                                           |
| parent-first runtime, support-state, command-run, human-request, or end-to-end behavior | focused runtime tests plus the relevant e2e lane                                                             |
| release                                                                                 | release checklist, package build, install smoke, docs/examples parity, relevant DB and e2e lanes             |

Use the heavier lane when a change crosses surfaces. Record skipped lanes with the exact scope reason.

## Docs-only changes

Run:

```bash
make check-docs
```

After moving or deleting public docs, also scan for stale links and redirect-only page language:

```bash
rg -n "deleted-page-name|deleted-folder-name|redirect-only|legacy entry" docs README.md .agents/standards -g '*.md'
```

Do not keep redirect-style wrapper pages after a public docs move. Delete old pages and update real links.

## Backend changes

Use focused pytest selectors while iterating, then run the applicable command matrix for the touched surface.

Core repo commands:

```bash
make check-api
make test-api-unit
make test-api-integration
make test-api-db
make test-api-e2e-bounded
make test-api-e2e-reviewed
make test-api-e2e-staged
```

Do not claim full backend completion from `make check-api` alone.

## Prompt and generated prompt docs

When prompt catalog inputs or generated prompt pages change, run:

```bash
make docs-prompt-generate
make docs-prompt-check
./.venv/bin/ruff check scripts/docs
./.venv/bin/mypy scripts/docs
```

Add focused prompt rendering tests for behavior changes.

## Release changes

Release-ready means code, tests, docs, examples, package resources, install behavior, and DB behavior agree.

Use:

- [Prepare a release](prepare-a-release.md)
- [Testing and release checklist](../reference/maintainers/testing-and-release-checklist.md)
- [Publish a release](../reference/maintainers/publish-a-release.md)

## Related pages

- [Maintain packaging](maintain-packaging.md)
- [Maintain database support](maintain-database-support.md)
- [Maintain docs](maintain-docs.md)
- [Test structure standard](../../.agents/standards/structure/test-structure.md)

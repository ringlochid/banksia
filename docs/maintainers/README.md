# Maintainer verification

The root [agent contract](../../AGENTS.md) owns repository policy, mandatory read order, the command matrix, delegation rules, and closeout requirements. The [root style contract](../../STYLE.md) owns measurable code standards. This page routes a maintainer from a public claim to its internal owner and executable proof; it does not replace either root file.

## Authority routes

Start at the [internal documentation router](../../docs-internal/README.md), then read the smallest owning page:

| Public subject | Internal owner |
| --- | --- |
| Workflow meaning, publication, Task pinning, and Starter/reference inventory | [Product and Workflow architecture](../../docs-internal/architecture/product-and-workflow.md) |
| Assignment, Attempt, Waves, waits, Checkpoints, replan, and exact Result | [Runtime architecture](../../docs-internal/architecture/runtime.md) |
| Shared workspace, projections, notes, deliverables, logs, and file references | [Workspace, files, and prompt architecture](../../docs-internal/architecture/workspace-files-and-prompt.md) |
| Model-visible behavior and operation teaching | [System-prompt architecture](../../docs-internal/architecture/system-prompts.md) |
| Task-member operation names, inputs, transfer, and authorization | [Runtime-tool interface](../../docs-internal/interfaces/runtime-tools.md) |
| Console, product API, semantic readbacks, and Operator boundary | [Console and Operator interface](../../docs-internal/interfaces/console-and-operator.md) |
| Operator conversation turns and question sets | [Operator conversation contract](../../docs-internal/interfaces/operator-conversation-contract.md) |
| Configuration, provider setup, sandbox, and credentials | [Configuration and provider operations](../../docs-internal/operations/configuration-and-providers.md) |
| Startup recovery, health, Activity, support, and projections | [Recovery and observability operations](../../docs-internal/operations/recovery-and-observability.md) |
| Installation, upgrade, reset, service, and packaging | [Package and reset operations](../../docs-internal/operations/package-and-reset.md) |
| Applicable checks and closeout evidence | [Root agent contract](../../AGENTS.md#testing-proof-and-commands) |

Durable accepted decisions live in the [architecture decision records](../../docs-internal/adr/README.md). Public schemas and maintained examples remain the external authoring contract.

## Documentation gate

While editing, use the focused commands:

```bash
make docs-format
make docs-format-check
make docs-contract-check
make docs-prompt-check
make test-docs
make docs-inventory
```

Before closing any maintained-doc change, run:

```bash
make check-docs
git diff --check
```

`make docs-format` writes maintained Markdown. The remaining commands above are nonmutating. `make check-docs` combines format check, authority/link/layer contracts, prompt-catalog validation, focused docs tests, and diff whitespace validation.

Prompt asset or catalog-input changes additionally require:

```bash
make docs-prompt-check
ruff check scripts/docs
MYPYPATH=src mypy scripts/docs
```

The prompt check compares shipped assets with their canonical source bodies and validates the maintained behavior scenarios.

## Generated API and Console contracts

When an HTTP route, payload, route usage, API-backed view model, or API reference changes, verify that tracked OpenAPI remains generated from the shipped routers:

```bash
make backend-openapi-check
make console-openapi-check
```

Use `backend-openapi-generate` or `console-openapi-generate` only when the owning implementation changed and a reviewed generated update is required. The product and support documents must remain route- and schema-separated.

For touched Console behavior, the applicable nonbrowser baseline is:

```bash
make console-format-check
make console-lint
make console-typecheck
make console-test
make console-test-integration
make console-build
```

Run `make console-e2e` for page-level navigation, interaction, layout, visual, or accessibility changes. Run `make console-e2e-real` when the claim crosses real controller persistence, restart/readback, or optimistic-currentness recovery. Route interception cannot substitute for the latter.

## Backend proof lanes

`make check-backend` runs Ruff, mypy, and pyright; it does not run tests.

| Target | Scope |
| --- | --- |
| `make test-backend` | Unit suite (`tests/unit`). |
| `make test-backend-integration` | Repo-native SQLite and runtime-template integration groups. |
| `make test-backend-db` | Disposable Docker/PostgreSQL integration groups. |
| `make test-backend-e2e-bounded` | Bounded end-to-end runtime scenarios. |
| `make test-backend-e2e-reviewed` | Reviewed progressive end-to-end lane. |
| `make test-backend-e2e-staged` | Staged progressive end-to-end lane. |

Run every lane applicable under the root contract to the touched boundary. Focused pytest is iteration evidence, not permission to omit the final applicable target. Mocks do not replace shipped persistence, runtime truth, public CLI/API behavior, or real browser proof.

## Workflow catalog proof

The shipped inventory is exactly eight provider-neutral Starters with narrow built-in grants where the responsibility needs them:

```text
decision-through-competing-prototypes
deep-research-and-decision-brief
experiment-and-replication-program
idea-to-validated-demo
incident-investigation-and-recovery
migration-and-modernisation
production-feature-delivery
security-audit-and-hardening
```

Maintained, non-installed advanced references are exactly:

```text
advanced-cross-layer-delivery
advanced-reviewed-code-change
advanced-technical-decision
```

Catalog closeout must prove:

- every YAML file parses through the shipped ingestion path and agrees with JSON serialization;
- filename stem equals Workflow ID;
- Starter and reference inventories are disjoint;
- all Starters recursively omit `provider`, and every capability is a supported narrow built-in grant on its exact Member;
- fresh/reset and installed-distribution libraries contain exactly the eight Starters and no advanced reference; and
- definition-backed Manager behavior covers safe sequence/parallel work, feedback-bearing repair, bounded batches, evidence disagreement, anti-relay behavior, nested joins, and failed-replication claim limits.

Use `make docs-contract-check`, `make docs-prompt-check`, `make test-docs`, the applicable Workflow integration/E2E lanes, and package verification together; no one lane proves the whole catalog.

## Package, install, and reset

Build and inspect the actual distribution with:

```bash
make package-build
make package-verify
```

`package-build` rebuilds Console assets and `dist/`. `package-verify` installs the built artifacts into a disposable environment and exercises shipped entry points, resources, application routes, and first-use behavior.

Database schema, package/install path, or public CLI/API truth also requires the reset gate named by the internal package owner. Run it only with an explicit disposable configuration and workspace. Test-only table creation, direct helper calls, or an existing developer database are not fresh/reset proof.

## Release automation

The Linux compatibility workflow runs on pull requests and pushes to `main`. It adds Ubuntu proof for the platform claimed by the public installation docs and runs the installed-distribution verifier with its isolated fake user-service manager.

The release workflow can be dispatched manually to rehearse its build and installed verification without entering the publication job. Publication runs only for a pushed `v*` tag. Before pushing that tag:

1. confirm every required platform check is green on the exact candidate;
2. confirm the tag equals `v` plus the package version;
3. confirm the `pypi` GitHub environment contains the `PYPI_API_TOKEN` secret required by `.github/workflows/release.yml`; and
4. confirm the target version and filenames do not already exist on PyPI.

The workflow builds and verifies the distributions in an unprivileged job, then passes those exact files to a separate environment-bound publication job. After it succeeds, compare the published hashes with the downloaded workflow artifacts, perform a clean-index `pipx` installation and CLI smoke test, and create the GitHub release with the verified distributions and `SHA256SUMS` attached. Never enable `skip-existing` for the production index or rebuild an existing version.

## Keep live provider proof tiny

Live provider proof tests the provider/package/HTTP seam, not the full Starter catalog. For each managed provider claimed by a release, use one disposable one- or two-Member Workflow and one bounded prompt: a greeting, a tiny brainstorm or council question, or a short research question. Prove the exact request and workspace, provider turn, controller records, and HTTP Result/readback boundary. Add at most one Operator clarification and only the minimum answer turn needed to complete it.

Larger Starter journeys, including `production-feature-delivery` and `deep-research-and-decision-brief`, belong to deterministic catalog, runtime, and static proof. They still require their distinct responsibility, review, file-reference, and exact-Result oracles, but they are not live-provider release probes. `make package-verify` remains the complete disposable installed-distribution proof; do not expand it into an expensive catalog journey.

Provider proof must use configured shipped Codex and Claude paths when the release claims them. Browser proof needs installed Playwright dependencies. PostgreSQL proof needs the repository Docker Compose environment. Service installation needs the native disposable lane for the claimed host. The Windows Actions workflow owns native NTFS, DACL, Job Object, Scheduled Task, SQLite, package, and installed-distribution proof; GitHub-hosted Windows jobs do not provide PostgreSQL service containers.

If an external prerequisite is unavailable, record the exact command, missing environment, affected claim, and owner. Inspected code is not executed proof, and an unavailable lane is not silently green.

## Final public-story audit

Before release:

1. compare CLI documentation with installed `--help`;
2. compare HTTP documentation with both generated OpenAPI documents and route source;
3. compare controller-tool documentation with the exact nine Task-member and eighteen Operator catalogs;
4. validate the public Workflow prose/schema/examples through the shipped ingestion path;
5. run docs inventory and exact searches for historical product names, removed operation names, old Starter IDs, version-era authority language, fixed-stage execution language, and managed-file claims;
6. confirm affirmative deferred-capability mentions are absent while explicit “not supported” boundaries remain accurate;
7. inspect every public link and documented command; and
8. compare the final diff with `AGENTS.md`, `STYLE.md`, and the smallest relevant standard under [`.agents/standards/`](../../.agents/standards/README.md).

Search findings need interpretation. Legitimate maintenance jobs, ordinary English, research provenance, and explicit absence statements are not shipped product support. Any surviving affirmative stale claim needs an exact owner and correction before closeout.

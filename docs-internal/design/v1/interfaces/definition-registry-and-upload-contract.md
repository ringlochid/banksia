# Definition Registry And Upload Contract

Status: Target

This page defines the frozen v1 definition contract across one shared controller-owned internal definition service: public/operator search, current detail, revision history, guarded upload, task-start resolution, and node-lane current-only lookup.

Use this page for lifecycle, authority, DB-truth ownership, and guarded-write rules. Use [API Schema Appendix](api-schema-appendix.md) for exhaustive request and response coverage and [api-machine-catalog.yaml](api-machine-catalog.yaml) for exact machine-readable route and MCP tool arguments plus result carriers.

## Canonical definition kinds

The canonical singular kind tokens are:

- `role`
- `policy`
- `workflow`

The plural list routes are:

- `/definitions/roles`
- `/definitions/policies`
- `/definitions/workflows`

## Core routes

The canonical definition-registry routes are:

- `GET /definitions/roles`
- `GET /definitions/policies`
- `GET /definitions/workflows`
- `GET /definitions/{kind}/{key}`
- `GET /definitions/{kind}/{key}/versions`
- `POST /definitions`

## Shared internal definition service

One controller-owned internal definition service owns currentness, revision append semantics, normalized read models, guarded upload validation, launch-time workflow resolution, and runtime structural-edit lookup.

That same service is reused by separate surfaces:

- the public/operator surface family collectively exposes search, get current detail, revision history, guarded upload, and task start through `/definitions`, `/tasks/start`, and `operator MCP`
- the callback/node lane does not get generic registry routes or operator MCP definition tools
- runtime structural edits use a separate internal current-only lookup path for role/policy resolution and revision pinning at commit time

## Quick lifecycle examples

- upload one new current revision for one role, policy, or workflow key
- reuse the surfaced current `structural_edit_palette` plus runtime current-only lookup before `add_child` or `update_child` so structural edits use real current keys instead of prompt guesses

## Registry truth model

After successful ingest or guarded upload:

- imported files are provenance and authoring inputs
- packaged seeds under `apps/api/src/autoclaw/definitions/seeds/**` are the committed authored and shipped seed source for repo-provided definitions
- explicit caller-selected `definitions_root` override trees and example YAML in the source tree are still only authoring inputs
- no repo-root definitions mirror is required by shipped paths
- registry identity rows plus immutable revision rows are authoritative definition truth
- stored definition revisions may keep the exact authored body as a structured document column for later reread
- launch-time compilation uses the current workflow revision selected by the registry identity row key
- launch-time compilation rejects stored workflow bodies whose internal `id` no longer matches that registry-owned workflow key
- launch-time compilation resolves only the role and explicit policy current rows referenced by that selected workflow revision
- runtime structural edits validate role/policy references against current registry truth
- compiled plan and runtime node truth pin the exact resolved workflow, role, and policy revisions used for that task or structural revision

Imported files do not outrank registry truth after successful ingest. That includes explicit `definitions_root` override trees and any tutorial or example YAML kept in the source tree.

Registry persistence closure:

- `workflow_definitions`, `role_definitions`, and `policy_definitions` are stable identity tables
- `workflow_revisions`, `role_revisions`, and `policy_revisions` are append-only revision tables
- identity tables own stable logical keys plus the current revision pointer
- revision tables own immutable authored content snapshots, revision numbers, actor/audit fields when recorded, and timestamps
- guarded upload appends new revision rows and atomically advances the current revision pointer
- concurrent uploads are serialized in DB and may both succeed as distinct revisions
- the current revision pointer advances in DB commit order
- the design does not use a single-table mutable version-column history model for registry truth
- the design does not use a draft/publish definition state machine

Concrete example:

If `C:/defs/review-role.yaml` was imported successfully, later runtime structural validation uses the stored registry row for `role/review-role`, not the original file path.

## Current-only lookup for runtime structural edits

The shared definition service is the canonical truth source for valid role and policy choices, but the live node lane uses it through a narrower current-only lookup path.

That means:

- operator/public callers may use the search/get/history surfaces when they need discovery, audit, upload, or task start
- dispatched parent/root planning does not treat generic `/definitions/...` browsing or revision-history reads as the normal live surface
- parent/root structural edits choose role/policy names from the already surfaced current `structural_edit_palette` in prompt or manifest context
- `add_child` and `update_child` do not guess role or policy names from prompt prose or transcript memory
- runtime resolves only current role/policy rows for those chosen names and still revalidates them at commit time

Revision-history rule:

- revision history remains operator/trusted-automation only
- revision history is for audit, provenance, and investigation rather than normal dispatched parent/root planning

Concrete example:

1. reread the current manifest, latest checkpoints, and surfaced `structural_edit_palette`
2. choose `review-role` and `review-policy` from that current surfaced palette
3. call `add_child` through the bound callback semantic tool lane
4. let the runtime validator resolve those names against current registry truth and pin the exact resolved role/policy revision numbers at commit time

## List, detail, and history reads

List routes return `DefinitionSummaryListResponse`. Detail reads return `DefinitionRevisionDetailResponse`. Revision-history routes return `DefinitionRevisionHistoryResponse`.

These public/operator surfaces exist so operators and trusted automation can answer:

- what keys exist
- what the current definition body is
- which revision is current
- which earlier revisions exist in history

Audience split:

- list/search plus current detail are operator/public discovery surfaces over the shared definition service
- task start reuses that same service to resolve the current workflow, role, and policy truth before runtime materialization commits
- revision-history read is an operator/trusted-automation audit surface only and not part of the normal live parent/root node surface

List, search, and history query rules:

- definition list/search routes use `q`, `limit`, `cursor`, and `sort`
- role list/search may additionally use `allowed_node_kind`
- policy list/search may additionally use `applies_to`
- detail read returns the current definition revision for that logical key
- version-history read uses `limit`, `cursor`, and `sort`

Machine-readable parameter and tool-result descriptions live in [api-machine-catalog.yaml](api-machine-catalog.yaml).

## Guarded upload rule

`POST /definitions` requires:

- `kind`
- `content` as exactly one definition body of the selected kind
- logical key from `content.id`

Guarded upload semantics:

- same `kind` plus logical key plus identical canonical normalized content hash as the current stored revision is a no-op
- changed accepted canonical content stores the next immutable revision row for that definition key and atomically advances the current revision pointer
- does not mutate the current or any historical revision row in place
- returns `200` on a no-op identical-content write
- returns `201` on successful guarded upload that created a new current revision
- returns `422` on invalid definition content

Canonical hash basis:

- hash the accepted canonical normalized definition body
- exclude transport-only wrapper fields such as request `kind`

For `PolicyDefinitionInput`, invalid definition content includes:

- `default_policy`
- `defaults`
- `defaults.retry_budget`
- `rules`
- `rules.allowed_tools`
- `rules.allowed_boundaries`
- `same_attempt_continue_limit`
- `same_attempt_redispatch_limit`
- authored same-session or continue-session preferences
- any `budget_spec` key other than `child_assignment_limit` or `retry_limit`

Canonical behavior is reject, not silent ignore, for richer-than-live policy grammar.

There is no required actor header in the frozen core contract. Authenticated lane identity may be recorded for audit, but actor transport is not frozen here.

Worked create example:

```text
POST /definitions
kind=workflow
content=<one exact WorkflowDefinitionInput with id "retry-review">

-> 201 Created
-> DefinitionRevisionDetailResponse { key: "retry-review", revision_no: 1, ... }
```

No-op example:

```text
POST /definitions
kind=workflow
content=<canonical content identical to current stored workflow/retry-review>

-> 200 OK
-> DefinitionRevisionDetailResponse { key: "retry-review", revision_no: 8, ... }
```

Worked update example:

```text
POST /definitions
kind=workflow
content=<one exact WorkflowDefinitionInput with id "retry-review">

-> 201 Created
-> DefinitionRevisionDetailResponse { key: "retry-review", revision_no: 8, ... }
```

Concurrent upload rule:

- if two callers upload different new content for the same logical key concurrently, DB serialization may commit both as distinct new revisions
- whichever upload commits later becomes the new current revision
- earlier committed revisions remain preserved in history
- there is no caller-supplied compare token in the public upload contract

## Launch-time compiler rule

Standard task start resolves:

- the current workflow revision for `workflow.key`
- only the referenced role and explicit policy definitions required by that workflow

The launch-time compiler owns:

- current workflow + role/policy definitions + task compose
- normalized compiled plan
- initial runtime graph/materialization at task start

Internal validation rule:

- guarded definition upload validates schema legality, role/policy reference legality, and dependency legality before the current revision pointer moves
- task start validates again against current truth before runtime materialization commits
- runtime structural adopt validates again before a new structural revision commits
- the validator is internal by design; it is not exposed as a public API or standard `operator MCP` surface

## Runtime structural-edit rule

Runtime structural CRUD is not a definition-registry write and does not invoke the launch-time compiler.

For `add_child` and `update_child`:

- the runtime validator checks candidate role/policy references against current registry truth
- the runtime validator pins the exact resolved role/policy revision numbers into the new adopted runtime truth
- explicit node `policy` resolves when present; otherwise no policy resolves
- runtime structural edits never inject a hidden workflow-level or role-level default policy
- if a policy resolves, only its `description`, `instruction`, and optional `budget_spec` participate
- parent/root policies may author only `child_assignment_limit`
- worker policies may author only `retry_limit`
- same-attempt redispatch and same-session continuity remain controller recovery/continuity behavior rather than authored policy
- the controller commits runtime truth only after that validation passes
- the runtime materializer/projector then regenerates `_runtime` projections

This keeps definition upload separate from runtime mutation.

That separation is important:

- definition-registry work changes reusable authored truth through guarded upload
- runtime structural CRUD changes one running flow only
- the two surfaces may validate against one another, but they are never the same lane
- after commit, execution follows pinned compiled/runtime revision truth rather than rereading moving registry head on every dispatch

## Named response coverage

The canonical named responses used by this surface are:

- `DefinitionSummaryListResponse`
- `DefinitionRevisionDetailResponse`
- `DefinitionRevisionHistoryResponse`

Field-level definitions live in [API Schema Appendix](api-schema-appendix.md).

## Removed from the live registry model

Do not keep these as live registry semantics:

- callback-bound runtime mutation through definition routes
- a draft/publish state machine for definitions
- provider/package-specific authored definition fields
- `parent_gate`-specific compatibility rules
- `BoundaryAction`-era legal-outcome matrices
- `url` or `uri` as surfaced runtime ref requirements

## Related contracts

- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [API schema appendix](api-schema-appendix.md)
- [Role and policy definition schema](role-and-policy-definition-schema.md)
- [Workflow definition schema](../workflows/workflow-definition-schema.md)
- [Guarded registry and runtime writes](guarded-registry-and-runtime-writes.md)
- [Definition ingest and task-start file contract](definition-ingest-and-upload-contract.md)

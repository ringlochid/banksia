# Definition authoring workbench

Status: Target

This page defines the V2 definition-authoring workbench surface.

## Core rule

The authoring workbench is the user-facing front door over controller-owned definition truth plus local pending authoring state.

It must not become:

- a second definition truth owner
- a hidden runtime-dispatch surface
- a draft-only execution lane that bypasses guarded apply and task start

The workbench may share shell chrome with runtime control surfaces, but it remains a separate major surface from live task execution.

## Canonical workbench capabilities

The workbench may provide:

- registry inspection of current roles, policies, and workflows
- flat draft create, open, save, publish, and delete actions
- local draft editing of one or more definition files
- local draft reset to the captured stored baseline or local starter baseline
- explicit re-materialize-current action when replacing a draft with the current stored revision is intended
- readback of normalized JSON draft shadows or baseline metadata when exact compare or stale inspection matters
- schema and legality validation
- explicit apply or import
- optional task-compose preview and post-apply task start

## Surface composition

The workbench should separate these authored concerns clearly:

- current registry browser
- draft workspace
- validation readback
- local reset versus current stored revision replacement
- explicit draft save versus apply or publish actions

Workflow-node editing should expose `description` and `instruction` as separate authored fields: `description` is node-purpose text, while `instruction` is optional node-local prompt guidance.

The workbench may collapse these into one page or switcher, but it must not blur saved draft state into stored current truth.

The workbench talks to backend-owned flat draft files under AutoClaw's configured data dir. Browser state may cache editor input transiently, but it is not the authoritative saved-draft surface.

The workbench and `/authoring` API own draft mutations. Operator MCP must not expose a parallel create, save, validate, publish, or delete editor lane.

## Surface rules

Rules:

- the workbench should show current stored truth and saved draft state as separate states
- editable authored bodies may stay YAML-first while the same flat draft also exposes backend-owned normalized JSON shadows for machine-exact inspection
- local reset must remain a draft-state operation; it must not imply a registry current refresh
- replacing a draft with current stored truth must be a separate explicit operation; it must not imply publish
- apply or import is explicit and separate from draft save
- task start remains a post-apply action over current controller truth
- exact flat draft, validation, staleness, collision, and publish semantics live in the definition authoring API and flat draft contract rather than this UI page
- task-compose preview is a separate read-only operation over current stored definitions, not an extension of draft validation or a draft execution path
- a ready preview shows each workflow node's resolved provider plus `provider_native_access` and `network_access` as `{effective, source}` values
- preview creates no task or runtime effects, and the workbench must explain that task start rereads current truth rather than relying on the preview as a reservation

## Non-goals

This contract does not define:

- final visual layout of the workbench
- backend draft-folder internals
- final backend route names or payload encoding
- a draft execution path that bypasses apply and task start

## Related contracts

- [Definition authoring API and flat draft contract](definition-authoring-api-and-flat-draft-contract.md)
- [Role and policy definition schema](role-and-policy-definition-schema.md)
- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
- [Console runtime surfaces](console-runtime-surfaces.md)
- [V1 definition registry and upload contract](../../v1/interfaces/definition-registry-and-upload-contract.md)

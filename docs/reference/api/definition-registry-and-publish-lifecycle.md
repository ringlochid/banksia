# Definition registry and publish lifecycle

This page defines the shipped DB-backed definition registry lifecycle for roles, policies, and workflows.

## Definition source of truth

File discovery is only a seed source.

Live definition truth after seeding or upload is the DB-backed registry, including immutable revisions and the current revision pointer.

Compiler and runtime launch paths read current definition truth from those registry rows.

The packaged resource mirror is the committed authored and shipped bootstrap input. Explicit local override trees may be used only when selected by the caller. Neither source outranks the DB-backed registry after seeding.

## Discovery and seeding

Current seeding behavior:

- choose the packaged seed root by default, with explicit local override only when the operator selects it
- parse seed YAML into role, policy, and workflow definition models
- create revision `1` for new definition keys
- for existing definition keys, reuse an existing revision when the candidate content hash already exists
- for existing definition keys, append a new immutable revision when the candidate content hash is new
- advance `current_revision_no` only when the current revision is still on the same seed track

Normal shipped init/reset/upgrade paths seed from the packaged mirror. Explicit override trees matter only when selected by the caller. Missing packaged seeds fail the shipped path instead of triggering repo fallback.

Shipped entrypoints that seed the registry include:

- `autoclaw init`
- `autoclaw db upgrade`
- `autoclaw db reset`

## Write lifecycle

The write lifecycle is service-driven:

1. load the current definition row under lock when it exists
2. hash the candidate content
3. if the content is unchanged, return the current revision without creating a new one
4. otherwise allocate the next revision number
5. validate workflow candidates against current role/policy registry truth
6. insert the new revision and advance `current_revision_no`

Shipped reseeding behaves differently from an ordinary update path for existing keys:

1. if a definition key is missing, create revision `1`
2. if a matching content hash already exists for that key, reuse the matching revision instead of creating a duplicate
3. if the packaged seed content is new for that key, append a new immutable revision
4. only advance `current_revision_no` when the current revision is still on the same seed track
5. preserve newer controller-selected currentness when reseed should not promote the packaged revision

## Validation and currentness rules

Current workflow upserts can fail without advancing currentness when:

- the workflow references a missing role or policy
- the workflow violates node-kind compatibility
- the workflow violates dependency or schema rules

Current reseeding preserves controller-owned currentness by refusing to hijack a newer current revision that no longer belongs to the same seed track.

## HTTP surface

Current shipped API routes keep registry truth under `/definitions` and task start under `/tasks/start`, and also expose backend-owned flat definition draft routes under `/authoring/*`.

Current shipped authoring facts are:

- one saved draft may exist for each `(kind, key)` under `drafts/definitions/{roles|policies|workflows}/{key}.yaml`
- draft metadata and normalized shadows live under `drafts/definitions/_metadata/` and `drafts/definitions/_normalized/`
- the YAML draft body is the editable draft truth; authoring readback still lists and opens a body-only draft before the next save rewrites canonical metadata
- `GET /authoring/definitions/{kind}/{key}/draft` returns a saved draft or a transient current-definition update draft when no saved draft exists
- draft save/delete writes mutate only backend-owned local draft state, not registry truth
- `POST /authoring/definitions/{kind}/{key}/draft/publish` publishes through the same DB-backed registry truth used elsewhere
- create drafts reject existing current registry keys with `name_collision`
- update drafts carry baseline revision and content hash; stale publishes return `stale` and do not overwrite newer registry truth
- operator MCP does not expose draft authoring tools; mutating draft authoring remains on the HTTP `/authoring` workbench API

Registry lifecycle is therefore no longer only a service plus CLI concern. Current HTTP also exposes a local pending-authoring lane over the same registry truth.

## Skill-specific rule

Current registry lifecycle does not include live skill registry rows or `skill_refs` writes in the shipped tree.

## Minimal example

```text
autoclaw init
  -> create schema
  -> seed the packaged definition mirror
  -> registry current_revision_no now points at revision 1 for shipped seeds

internal workflow update
  -> validate candidate
  -> insert revision 2
  -> advance workflow_definitions.current_revision_no to 2

later shipped reseed of that same workflow key
  -> reuse the matching revision if the hash already exists
  -> append a new packaged revision if the hash is new
  -> keep revision 2 current if controller currentness moved off the seed track
```

## Related pages

- [Definition and task-compose YAML contract](definition-and-task-compose-yaml-contract.md)

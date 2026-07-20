# Maintain docs

Use this guide when adding, moving, deleting, or rewriting docs.

AutoClaw docs must keep public product docs, public reference docs, and internal canon separate.

Public docs should not expose internal authority or verification headers. Internal canon, ADRs, standards, and generated internal readbacks may use authority metadata when the metadata helps maintainers distinguish target, current, reference, template, or accepted decision surfaces.

## Placement rules

Use:

- `docs/start/**` for first success paths
- `docs/concepts/**` for mental models
- `docs/guides/**` for practical user workflows
- `docs/help/**` for symptoms, fixes, and common questions
- `docs/maintainers/**` for maintainer workflows
- `docs/reference/**` for exact CLI, API, definition, operator, and maintainer reference
- `docs-internal/**` for design truth, current contrast, ADRs, and internal implementation canon

Do not put active implementation-program material into public onboarding, concept, or troubleshooting pages.

## No-wrapper rule

After moving or deleting a public page:

- delete the old page
- update real links
- let missing old paths fail visibly

Do not keep redirect-style wrappers or pages that only point readers somewhere else.

## Page shape rules

Use one page type per page:

- concept: explain the model
- guide: help a reader complete one workflow
- reference: list exact fields, commands, routes, or matrices
- troubleshooting: symptom, checks, cause, fix
- maintainer guide: maintainer task, decision points, verification

Open with the page's main claim or task. Keep headings descriptive and links human-readable.

## Validation

For docs-only changes, run:

```bash
make check-docs
```

Use `make docs-format` to rewrite maintained Markdown before rerunning the gate.

After deleting, renaming, or moving pages, scan for stale links:

```bash
rg -n "old-page-name|old-folder-name" README.md docs docs-internal .agents -g '*.md'
```

After moving public docs, scan for redirect-only page language:

```bash
rg -n "redirect-only|legacy entry|old page|new owner" docs README.md -g '*.md'
```

## Docs update checklist

- changed behavior has an updated public doc or reference owner
- public docs do not contradict current shipped behavior
- exact command and schema details live in reference pages
- troubleshooting links to reference rather than duplicating whole contracts
- examples match current role, policy, workflow, and task-compose schemas
- docs navigation follows reader intent, not a mechanical folder dump
- no stale moved-page wrappers remain

## Related pages

- [Docs structure guide](../../.agents/standards/docs/docs-structure.md)
- [Troubleshooting](../help/troubleshooting.md)
- [Choose a verification lane](choose-a-verification-lane.md)

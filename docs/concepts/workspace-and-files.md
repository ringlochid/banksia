# Workspace and files

Every Task has one selected provider-visible workspace. All Members work in that same native filesystem and use their provider's ordinary file, search, editor, shell, and binary tools.

Banksia does not create a branch, checkout, or write-isolated directory per Member. Managers must sequence overlapping writes or divide ownership into credibly disjoint paths.

## Task directory

Task admission creates one collision-safe directory inside the workspace:

```text
.banksia/
└── t_<id>/
    ├── manifest.md
    ├── workflow-note.md       # present only when the Workflow has a note
    ├── notes/
    ├── artifacts/
    └── command-runs/
```

The full Task ID identifies this directory and is available in provider context. Banksia creates `notes/`, `artifacts/`, and `command-runs/` before the first provider turn starts.

## Controller truth and projections

The controller database, not the filesystem, owns Tasks, team revisions, Assignments, Attempts, provider turns, waits, Waves, Checkpoints, controls, and Results.

Only these organization files are controller projections:

- `manifest.md` is controller-generated from the current Task organization and selected Member configurations. It is regenerated after an accepted structural replan; the projection is not itself authored.
- `workflow-note.md` projects the shared authored Workflow note when one exists.

A projection can be rebuilt from controller truth and cannot authorize a runtime transition. Banksia does not project Assignment, Checkpoint, Work Plan, `instructions.md`, or `input.md` files.

## Loose notes and deliverables

`notes/` is proportional shared working memory. Use it when a durable research ledger, assumptions list, repair checklist, or delegation rationale will reduce rediscovery. Do not require ceremonial notes for small work.

`artifacts/` is a convention for loose reviewable deliverables such as a research report, option matrix, architecture diagram, review record, browser recording, or patch. Source code, tests, and project documentation should remain at their natural project paths.

Despite the directory name, Banksia has no managed Artifact resource. It does not assign a file ID, version, hash, current pointer, approval state, or snapshot lifecycle to these files. They remain ordinary mutable workspace bytes.

## Command Run output

Each managed Command Run writes its complete observed output to:

```text
.banksia/t_<id>/command-runs/c_<id>/output.log
```

Product and Operator reads return bounded, sanitized output pages plus facts such as whether output is complete, missing, changed, or bounded. The full log remains in the workspace. It is command execution output, not a database projection or an archive of unrelated provider-native shell activity.

## File references

Task start, Assignments, Checkpoints, and Human Requests use one generic navigation value:

```yaml
path: .banksia/t_7m4k2d9x/artifacts/review-report.md
description: Independent review and prioritized findings
```

`path` is required and `description` is optional. The path must use Banksia's normalized, slash-separated workspace-relative grammar and identify an existing regular file. This same logical grammar is used on Linux, macOS, and Windows. Banksia rejects:

- absolute paths, drive or URI prefixes, backslashes, `..`, and glob syntax;
- duplicate normalized paths in one owning message;
- missing paths and non-regular files; and
- any path with a symbolic-link component.

Validation proves only what existed at the owning boundary. A file reference does not copy bytes, freeze content, grant access, or make later reads canonical. Another Member opens the current file with native provider tools.

## Three honest handoffs

| Kind | Reference | What the receiver should do |
| --- | --- | --- |
| Project file | `{path: "src/payments/service.py", description: "Implementation reviewed in this Checkpoint"}` | Inspect the current tracked file and relevant Git diff. If it changed after the report, identify the reviewed revision or say that reinspection is required. |
| Working note | `{path: ".banksia/t_7m4k2d9x/notes/investigation.md", description: "Observed symptoms and rejected causes"}` | Treat it as mutable coordination memory. If it is missing or stale, report that fact instead of inventing its contents. |
| Reviewable deliverable | `{path: ".banksia/t_7m4k2d9x/artifacts/review-report.md", description: "Ranked independent findings"}` | Open the current report and verify consequential claims against current project state. Do not describe the file as immutable or approved merely because it was referenced. |

When exact byte-for-byte reconstruction matters, the workspace's version control, dataset preservation, or another user-owned archival system must provide it.

## Version control

Banksia does not detect repositories, inspect tracked paths, run Git, or change `.gitignore`, `.git/info/exclude`, or another version-control setting. A Task's `.banksia/t_<id>/` directory is ordinary workspace content: you may commit it, ignore it, archive it, or remove it according to your own workspace policy.

An existing `.banksia/` directory may contain unrelated project files. Banksia preserves those files and owns only the collision-safe `t_<id>/` directories it creates. This does not protect project files from concurrent Member edits and does not commit, branch, stash, or roll back work.

See [Runtime and results](runtime-and-results.md) for controller ownership and [Run and operate Tasks](../guides/run-and-operate.md) for inspecting Results and referenced files.

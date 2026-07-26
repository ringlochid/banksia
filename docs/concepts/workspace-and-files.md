# Workspace and files

Providers work in the Task's selected workspace. Banksia keeps native filesystem access useful while preserving a clear boundary between controller truth and files.

## Task directory

Task admission creates a collision-safe directory under the workspace:

```text
.banksia/
└── t_<id>/
    ├── manifest.md
    ├── workflow-note.md       # only when the Workflow has a note
    ├── notes/
    ├── artifacts/
    └── command-runs/
```

The Task ID is supplied in the provider context. Banksia creates `notes/`, `artifacts/`, and `command-runs/` before the first provider Dispatch starts.

## What Banksia owns

The controller database is canonical for Tasks, teams, Assignments, Attempts, Dispatches, waits, Waves, Checkpoints, file-reference values, controls, and Activity.

Only two files are controller projections:

- `manifest.md` is the current organization chart. It lists the complete hierarchy and each Member's authored configuration, but not runtime progress.
- `workflow-note.md` contains the authored team note when one exists.

The manifest is regenerated after a structural replan. A projection can be rebuilt from database truth and never decides runtime legality.

Command Run logs are controller-managed execution output, not database projections. The controller stores their path and bounded status/output details; the full log stays under `command-runs/`.

## Notes and artifact files

`notes/` and `artifacts/` are conventions for ordinary mutable files, not controller resource types.

Use `notes/` for shared working memory that helps coordination or recovery, such as:

- a research ledger;
- delegation rationale;
- assumptions and open questions;
- a repair checklist; or
- review findings still being reconciled.

Use `artifacts/` for a structured deliverable another Member or the user should inspect, such as:

- an implementation plan;
- a research report;
- an architecture diagram;
- a review or verification record;
- an image or browser recording; or
- a patch file.

Keep source code, tests, and project documentation at their natural project paths. Do not copy every edit or tool result into `artifacts/`. A short Checkpoint is often enough.

Members use provider-native filesystem, search, editor, shell, and binary tools. Banksia does not add generic list, read, write-note, or artifact operations.

## File references

Assignments, Checkpoints, Human Requests, and Task start use one generic navigation value:

```yaml
path: .banksia/t_7m4k2d9x/artifacts/review-report.md
description: Independent review and prioritized findings
```

The description is optional. The path may name a project file, note, artifact file, organization projection, or Command Run log beneath the selected workspace.

A file reference does not copy bytes, grant permission, freeze content, publish an artifact, or assign a file ID, hash, version, or lifecycle. It simply tells the receiver which current loose file to open and why. If exact content matters, the receiver should report a missing or changed file honestly.

Banksia does not project Assignments or Checkpoints into Markdown or JSON files. `get_current_context` is the typed readback for the complete current Assignment, Continuation, team context, Work Plan, legal actions, capabilities, and Task paths.

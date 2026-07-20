# Run a bugfix flow

Status: Target

This tutorial is the short bugfix walkthrough for the canonical `reviewed-change-release` workflow shape.

It mirrors `../workflows/examples/reviewed-change-release.md` rather than the richer staged delivery reference.

## Walkthrough

1. Launch the task and open `_runtime/workflow-manifest.md`. Confirm the root, `implementation_subtree`, and `release_closure` nodes are present.
2. Open `_runtime/attempts/<attempt_id>/assignment.md` for root. Root should see current criteria plus the current whole-workflow structure.
3. Root stages `implementation_subtree` with `assign_child` and then emits `yield`.
4. `implementation_subtree` is dispatched and stages its direct children in order:
    - `investigate_issue`
    - `implement_change`
    - `review_change`
5. After `investigate_issue`, inspect:
    - terminal checkpoint summary
    - `findings_report`
6. After `implement_change`, inspect:
    - terminal checkpoint summary
    - `change_patch`
    - `verification_report`
7. After `review_change`, inspect:
    - terminal checkpoint summary
    - `review_report`
8. When `implementation_subtree` is redispatched, it should review those child checkpoints, current subtree criteria, and surfaced artifacts before deciding whether to stage more work or end `green`.
9. When root is redispatched, it should read:
    - the latest subtree checkpoint
    - current subtree artifacts
    - current root closure criteria
10. If the workflow includes `release_closure`, root stages that child next. `release_closure` consumes surfaced release evidence and publishes `closure_report`.
11. Root closes the task only after current whole-flow evidence is sufficient, `release_green` is committed, and root emits `green`.

## What to look for in the files

- assignment files tell you the current bounded mission
- checkpoint files tell you what just happened and what should happen next
- artifact refs tell you which durable evidence is current
- the manifest tells you whether the structure itself changed during the flow
- dispatch-local monitoring files under `_runtime/dispatch/<dispatch_id>/...` are observability projections only, not ordinary task truth

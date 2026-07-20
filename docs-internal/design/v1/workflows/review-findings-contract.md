# Review Findings Contract

Status: Target

This page freezes the live v1 contract for review, QA, audit, and similar evidence-checking work.

Review is authored as ordinary child work in v1. It is not a special gate mode or hidden subtree privilege.

## Review node contract

Review/QA/audit nodes use the same assignment surface as any other node:

- `summary`
- `instruction`
- `criteria`
- `consumes`
- `produces`
- optional `transient_refs`

The review node consumes only what the current assignment explicitly surfaces.

That usually includes:

- the reviewed artifacts
- current criteria
- any prior checkpoint refs the review must understand
- any curated supporting docs surfaced through `consumes`

In ordinary review assignments:

- `summary` names the subject under review
- `instruction` constrains the audit method and scope
- `criteria` carries the current requirements the review must verify
- `consumes` surfaces the artifacts, checkpoints, and supporting docs to read
- `produces` declares the durable report slots the review must publish

## Review findings outputs

Review findings live in ordinary durable artifacts declared in `produces`. The review also closes through one ordinary terminal checkpoint for the current assignment.

Typical produce slots include:

- review findings report
- QA report
- audit summary
- release-readiness report

The durable description for those outputs comes from the authored workflow YAML produce-slot description, not from ad hoc review-only carrier naming.

There is no special review-specific output family in the live v1 model.

### Concrete review artifact example

```yaml
produces:
    artifacts:
        - slot: review_report
          description: Review findings and disposition for the subtree.
          file_hint: review_report.md
```

Example review checkpoint core:

```yaml
checkpoint_kind: terminal
outcome: green
summary: Review completed; patch matches the findings report, but one retry-path test is still missing.
next_step: Stage a follow-up engineering assignment for the missing retry-path coverage.
artifacts:
    - slot: review_report
      version: 1
      path: C:/tasks/task_2026_0042/outputs/artifacts/review_change/review_report/review_report.v01.md
      description: Review findings and disposition for the subtree.
```

The checkpoint outcome remains `green` because the review assignment completed. The missing test is recorded as review content, not as a second review-only attempt result.

## Result rules

Review/QA/audit nodes normally end with:

- `green`
- `blocked`

Rules:

- `green` means the review assignment completed
- `green` does not mean the reviewed subject necessarily passed
- negative findings usually still produce review `green`
- there is no separate `pass`, `fail`, or `incomplete` attempt result for review work
- approval, rejection, and evidence-gap details belong in the checkpoint summary and review artifacts
- `blocked` means the review could not complete as assigned

When review returns `green`, every produce required by the current assignment must already be published.

## Parent/root relationship

Review/QA/audit nodes publish:

- one authoritative latest terminal checkpoint, with superseded terminal rows retained as history
- referenced durable artifacts
- optional transient refs when explicitly surfaced

Parent/root then reads those ordinary surfaces and decides whether to:

- stage follow-up child work
- structurally edit the owned subtree
- release upward

Review findings do not force parent/root `green` by themselves.

## Evidence rule

If the review needs exact criteria, reviewed artifacts, prior checkpoints, or supporting docs, those must be surfaced explicitly in the assignment.

Review must not rely on:

- hidden subtree access
- review-only carrier families
- transcript-only memory
- old manifest slices or gate callbacks

## Related contracts

- [Parent/root release and closure](parent-root-release-and-closure.md)
- [Parent review and replan](parent-review-and-replan.md)
- [Runtime boundary and controller loop contract](../architecture/runtime-boundary-and-controller-loop-contract.md)

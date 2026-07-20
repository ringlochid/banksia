# Historical packet prose examples

Status: Reference

This page preserves old packet/bundle-era prose examples for migration search only.

These packet families are not part of the live v1 prompt contract. Use the live owner pages instead:

- [Contract](../contract.md)
- [Field Renderers](../field-renderers.md)
- [Worker Context Contract](../../architecture/worker-context-contract.md)
- [Artifact Ref And Storage Contract](../../architecture/artifact-ref-and-storage-contract.md)
- [Runtime Boundary And Controller Loop Contract](../../architecture/runtime-boundary-and-controller-loop-contract.md)

## `result_record_summary_example_v1`

```yaml
result_record:
    attempt_key: inspect_resume_path.attempt-02
    assignment_key: inspect_resume_path.assign-01
    outcome: green
    summary: >
        Patched the bounded resume-path watchdog stall, reran the required
        verification steps, and produced the required patch plus test evidence for
        the current assignment only.
```

## `handoff_packet_summary_example_v1`

```yaml
handoff_packet:
    handoff_ref: patch_scope.v01
    slot: patch_scope
    summary: >
        The bounded patch scope remains limited to the resume-path watchdog logic.
        Do not rewrite unrelated retry, closure, or provider transport behavior.
    next_expectations:
        - publish one patch artifact
        - publish one verification report
    constraints:
        - stay inside the bounded assignment
```

## `ordinary_review_output_summary_example_v1`

```yaml
ordinary_review_output_summary:
    artifact_refs:
        - implementation_review_report.v01
        - implementation_audit_bundle.v01
    summary: >
        Review produced ordinary parent-facing outputs for the current subtree.
        Consume them together with the latest child outputs before the next bounded
        parent decision.
```

## `root_release_bundle_summary_example_v1`

```yaml
root_release_bundle:
    handoff_ref: final_release_bundle.v01
    slot: final_release_bundle
    summary: >
        Root verification is complete and bounded release work may now proceed
        against the curated release inputs only.
    next_expectations:
        - consume only the listed release inputs
        - emit green only when bounded release work is complete
    constraints:
        - do not reopen implementation scope
        - do not widen task scope
```

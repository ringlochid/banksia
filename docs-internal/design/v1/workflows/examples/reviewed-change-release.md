# Reviewed change release workflow reference

Status: Target

This page provides the canonical reviewed change workflow example for the live v1 contract.

```mermaid
flowchart TD
    A["root"] --> B["change_subtree"]
    A --> C["release_closure"]
    B --> D["scope_change"]
    B --> E["implement_change"]
    B --> F["review_change"]
```

Figure: `reviewed-change-release` adds one parent subtree and one ordinary release child, while keeping review and release as authored work.

The YAML below is shown in canonical file form for CLI scan/import.

In this repo, the packaged seed under `apps/api/src/autoclaw/definitions/seeds/workflows/reviewed_change_release.yaml` is the committed authored and shipped seed source for this example. A caller may select an explicit `definitions_root` override tree for import or seed work, but no repo-root workflow fixture mirror is required by shipped paths. After seed or import, later compile and runtime paths follow the registry current revision rather than rereading seed or override files.

```yaml
kind: workflow
id: reviewed-change-release
description: Scope, implement, review, and close one engineering change with parent-owned handoff checks.
root:
    id: root
    role: root_planning_lead
    policy: standard-root
    description: Preserve the task purpose, verify scoped implementation and review evidence, and close from current controller truth.
    instruction: >-
      Read manifest, assignment, child checkpoints, surfaced refs, and criteria before release. Route weak scope, implementation, verification, or review evidence back through the subtree before closure.
    criteria:
        - slot: root_delivery_rules
          description: Root acceptance criteria.
          criteria:
              - final closure happens only after root verifies current scope, patch, review, and verification evidence
              - broad or weak evidence is routed to scoping, implementation, review, verification, or replan instead of release
        - slot: root_closure_criteria
          description: Final release criteria.
          criteria:
              - release work uses only surfaced evidence and current criteria
              - release work does not reopen implementation scope
    children:
        - id: change_subtree
          role: planning_lead
          policy: standard-parent
          description: Coordinate scoping, implementation, and ordinary review work for the bounded change.
          instruction: >-
            Prepare child assignments with purpose, refs to read first, constraints, criteria, required outputs, known risks, and untouched areas. Inspect each checkpoint before routing the next child.
          criteria:
              - slot: change_subtree_requirements
                description: Local execution requirements for the change subtree.
                criteria:
                    - scope, implementation, and review stay inside the current subtree
                    - each child checkpoint explains evidence read, reasoning, criteria status, and next action
                    - review evidence must address the current patch and verification evidence
          child_defaults:
              criteria:
                  - change_subtree_requirements
          children:
              - id: scope_change
                role: researcher
                policy: standard-worker
                description: Inspect task purpose, constraints, relevant context, and risks, then publish the scoped change brief.
                instruction: >-
                  Publish only the facts, constraints, uncertainties, and implementation implications needed by downstream work.
                produces:
                    artifacts:
                        - slot: change_scope_report
                          file_hint: change_scope_report.md
                          description: Scoped findings and constraints needed by downstream implementation.
              - id: implement_change
                role: engineer
                policy: standard-worker
                description: Implement the bounded change from current scope evidence and publish patch plus verification evidence.
                instruction: >-
                  Read the scope report and criteria before editing. Keep patch and verification scoped, and checkpoint residual risks.
                consumes:
                    artifacts:
                        - slot: change_scope_report
                criteria:
                    - slot: implement_change_delivery_criteria
                      description: Delivery criteria for the implementation step.
                      criteria:
                          - patch matches the scoped assignment
                          - verification evidence supports the claimed fix
                          - checkpoint names evidence read, commands or checks run, and any residual risk
                produces:
                    artifacts:
                        - slot: change_patch
                          file_hint: change_patch.diff
                          description: Patch for the scoped change.
                        - slot: verification_report
                          file_hint: verification_report.md
                          description: Verification evidence for the scoped change.
              - id: review_change
                role: reviewer
                policy: standard-worker
                description: Critically review current implementation evidence and publish a bounded review report.
                instruction: >-
                  Review current patch, verification evidence, and criteria. Record approval, rejection, evidence gaps, and residual risk.
                consumes:
                    artifacts:
                        - slot: change_patch
                        - slot: verification_report
                    criteria:
                        - slot: change_subtree_requirements
                produces:
                    artifacts:
                        - slot: review_report
                          file_hint: review_report.md
                          description: Review findings and review disposition for the subtree.
        - id: release_closure
          role: release_operator
          policy: standard-worker
          description: Perform final bounded release work from current surfaced implementation and review evidence.
          instruction: >-
            Use only surfaced scope, implementation, verification, review evidence, and closure criteria. Report release gaps instead of reopening scope.
          consumes:
              artifacts:
                  - slot: change_scope_report
                  - slot: change_patch
                  - slot: verification_report
                  - slot: review_report
              criteria:
                  - slot: root_closure_criteria
          produces:
              artifacts:
                  - slot: closure_report
                    file_hint: closure_report.md
                    description: Final bounded release or closure report.

```

## Expected runtime path

Typical execution order is:

1. root dispatch
2. `change_subtree` assignment
3. `scope_change`
4. `implement_change`
5. `review_change`
6. root review of current subtree evidence
7. `release_closure`
8. root final release decision

The authored tree does not force that exact order, but it gives runtime enough structure to make each step explicit through assignments, checkpoints, and durable artifact refs.

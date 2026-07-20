# Feature implementation workflow example

This example mirrors the shipped `feature-implementation` workflow fixture.

```yaml
kind: workflow
id: feature-implementation
description: Plan, implement, verify, review, and release one feature in an existing product context.
root:
    node_key: root
    kind: root
    role_id: root_planning_lead
    policy_id: standard-root
    description: Preserve feature intent and release only when integration, verification, and review evidence agree.
    instruction: >-
      Keep feature work integrated with existing product contracts and patterns. Route scope contradictions to review before implementation.
    criteria:
        - slot: feature_release_criteria
          description: Hard criteria for feature release.
          criteria:
              - feature plan explains user value, existing product context, integration points, acceptance criteria, and non-goals
              - implementation, verification, and review evidence refer to the same feature scope
              - unresolved integration, regression, or acceptance risks block release
    children:
        - node_key: inspect_existing_context
          kind: worker
          role_id: researcher
          policy_id: standard-worker
          description: Inspect the existing product context, patterns, constraints, and relevant evidence.
          instruction: >-
            Publish only context needed to plan and implement the feature safely.
          produces:
              artifacts:
                  - slot: existing_context_report
                    file_hint: existing_context_report.md
                    description: Existing product context, patterns, integration points, constraints, and risks.
        - node_key: plan_feature_integration
          kind: worker
          role_id: product_planner
          policy_id: standard-worker-human-request
          description: Plan the feature scope, integration strategy, acceptance criteria, and non-goals.
          instruction: >-
            Tie feature value to existing product behavior and avoid widening into unrelated product work.
          consumes:
              artifacts:
                  - slot: existing_context_report
          produces:
              artifacts:
                  - slot: feature_integration_plan
                    file_hint: feature_integration_plan.md
                    description: Feature scope, integration plan, acceptance criteria, non-goals, and risks.
        - node_key: review_feature_scope
          kind: worker
          role_id: scope_reviewer
          policy_id: standard-worker-human-request
          description: Review the feature plan for contradictions, missing prerequisites, and acceptance-risk gaps.
          instruction: >-
            Check whether the planned feature can be built cleanly inside existing product constraints.
          consumes:
              artifacts:
                  - slot: existing_context_report
                  - slot: feature_integration_plan
              criteria:
                  - slot: feature_release_criteria
          produces:
              artifacts:
                  - slot: feature_scope_review
                    file_hint: feature_scope_review.md
                    description: Scope and feasibility review for the feature plan.
        - node_key: implement_feature
          kind: worker
          role_id: engineer
          policy_id: standard-worker
          description: Implement the accepted feature scope.
          instruction: >-
            Read context, plan, and scope review first. Keep the patch integrated and bounded.
          consumes:
              artifacts:
                  - slot: existing_context_report
                  - slot: feature_integration_plan
                  - slot: feature_scope_review
          criteria:
              - slot: feature_implementation_criteria
                description: Hard implementation criteria for the feature.
                criteria:
                    - patch implements accepted feature scope and preserves existing contracts
                    - checkpoint explains changed areas, evidence read, checks run, and residual risk
          produces:
              artifacts:
                  - slot: feature_patch
                    file_hint: feature_patch.diff
                    description: Patch for the bounded feature implementation.
        - node_key: verify_feature
          kind: worker
          role_id: test_verifier
          policy_id: standard-worker-command-run
          description: Verify the feature behavior and integration expectations.
          instruction: >-
            Verify acceptance criteria and regression-sensitive existing behavior. Name untested areas.
          consumes:
              artifacts:
                  - slot: feature_integration_plan
                  - slot: feature_patch
              criteria:
                  - slot: feature_implementation_criteria
          produces:
              artifacts:
                  - slot: feature_verification_report
                    file_hint: feature_verification_report.md
                    description: Verification evidence for feature behavior and integration.
        - node_key: review_feature
          kind: worker
          role_id: code_reviewer
          policy_id: standard-worker
          description: Review the feature implementation and verification evidence.
          instruction: >-
            Focus on correctness, existing-pattern fit, regression risk, security implications, and missing tests.
          consumes:
              artifacts:
                  - slot: feature_integration_plan
                  - slot: feature_patch
                  - slot: feature_verification_report
              criteria:
                  - slot: feature_release_criteria
          produces:
              artifacts:
                  - slot: feature_review_report
                    file_hint: feature_review_report.md
                    description: Review findings for the feature implementation.
        - node_key: release_closure
          kind: worker
          role_id: release_operator
          policy_id: standard-worker
          description: Perform final bounded feature release or closure work from current surfaced evidence.
          instruction: >-
            Use only feature plan, patch, verification, review evidence, and release criteria.
          consumes:
              artifacts:
                  - slot: feature_integration_plan
                  - slot: feature_patch
                  - slot: feature_verification_report
                  - slot: feature_review_report
              criteria:
                  - slot: feature_release_criteria
          produces:
              artifacts:
                  - slot: closure_report
                    file_hint: closure_report.md
                    description: Final feature release or closure report.
```

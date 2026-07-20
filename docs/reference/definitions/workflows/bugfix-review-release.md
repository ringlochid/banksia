# Bugfix review release workflow example

This example mirrors the shipped `bugfix-review-release` workflow fixture.

```yaml
kind: workflow
id: bugfix-review-release
description: Diagnose, fix, verify, review, and release one defect with explicit evidence gates.
root:
    node_key: root
    kind: root
    role_id: root_planning_lead
    policy_id: standard-root
    description: Preserve the defect-fix purpose, coordinate specialist work, and release only when current criteria and evidence are satisfied.
    instruction: >-
      Treat child green as evidence, not proof. Use review, verification, failure analysis, or replan when evidence is weak.
    criteria:
        - slot: root_bugfix_release_criteria
          description: Hard criteria for defect-fix release.
          criteria:
              - root understands the reported defect, expected behavior, and accepted fix scope
              - current patch, verification, and review evidence all address the same defect
              - unresolved high-risk defects block release
    children:
        - node_key: triage_defect
          kind: worker
          role_id: bug_triage
          policy_id: standard-worker
          description: Reproduce, narrow, and explain the defect before implementation.
          instruction: >-
            Publish reproducible findings, rejected leads, likely failing path, and next recommended assignment.
          produces:
              artifacts:
                  - slot: triage_report
                    file_hint: triage_report.md
                    description: Defect reproduction, likely cause, scope, and uncertainties.
        - node_key: plan_fix
          kind: worker
          role_id: delivery_planner
          policy_id: standard-worker
          description: Convert triage evidence into a bounded fix package.
          instruction: >-
            Plan the narrow fix, dependencies, criteria, risks, and verification gates. Do not implement.
          consumes:
              artifacts:
                  - slot: triage_report
          produces:
              artifacts:
                  - slot: fix_plan
                    file_hint: fix_plan.md
                    description: Bounded fix plan and verification strategy.
        - node_key: implement_fix
          kind: worker
          role_id: bug_fix_engineer
          policy_id: standard-worker
          description: Implement the bounded defect fix from triage and plan evidence.
          instruction: >-
            Read triage and plan first. Keep the patch scoped and publish residual risk.
          consumes:
              artifacts:
                  - slot: triage_report
                  - slot: fix_plan
          criteria:
              - slot: fix_implementation_criteria
                description: Hard implementation criteria for the defect fix.
                criteria:
                    - patch addresses the diagnosed defect without unrelated refactor
                    - checkpoint explains evidence read, changed files, and residual risk
          produces:
              artifacts:
                  - slot: change_patch
                    file_hint: change_patch.diff
                    description: Scoped defect-fix patch.
        - node_key: verify_fix
          kind: worker
          role_id: test_verifier
          policy_id: standard-worker
          description: Verify the defect fix against current criteria.
          instruction: >-
            Verify intended behavior with reproducible commands or artifacts and name untested areas.
          consumes:
              artifacts:
                  - slot: triage_report
                  - slot: change_patch
              criteria:
                  - slot: fix_implementation_criteria
          produces:
              artifacts:
                  - slot: verification_report
                    file_hint: verification_report.md
                    description: Verification evidence for the defect fix.
        - node_key: review_fix
          kind: worker
          role_id: code_reviewer
          policy_id: standard-worker
          description: Review the fix patch and verification evidence.
          instruction: >-
            Publish findings with severity, reasoning, approval or rejection, and evidence gaps.
          consumes:
              artifacts:
                  - slot: change_patch
                  - slot: verification_report
              criteria:
                  - slot: root_bugfix_release_criteria
          produces:
              artifacts:
                  - slot: review_report
                    file_hint: review_report.md
                    description: Critical review of patch and verification evidence.
        - node_key: analyze_failure
          kind: worker
          role_id: failure_analyst
          policy_id: standard-worker
          description: Analyze repeated failure or blocked evidence when fix, verification, or review stalls.
          instruction: >-
            Recommend retry, specialist reassignment, structural replan, or blocked closure from current evidence.
          consumes:
              artifacts:
                  - slot: triage_report
                  - slot: verification_report
                  - slot: review_report
          produces:
              artifacts:
                  - slot: failure_analysis
                    file_hint: failure_analysis.md
                    description: Failure analysis and next-action recommendation.
        - node_key: release_closure
          kind: worker
          role_id: release_operator
          policy_id: standard-worker
          description: Perform final bounded defect-fix release work from current surfaced evidence.
          instruction: >-
            Use only triage, patch, verification, review, and release criteria. Report gaps instead of reopening scope.
          consumes:
              artifacts:
                  - slot: triage_report
                  - slot: change_patch
                  - slot: verification_report
                  - slot: review_report
              criteria:
                  - slot: root_bugfix_release_criteria
          produces:
              artifacts:
                  - slot: closure_report
                    file_hint: closure_report.md
                    description: Final release or closure report for the defect fix.
```

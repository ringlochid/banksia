# Planning only workflow example

This example mirrors the shipped `planning-only` workflow fixture.

```yaml
kind: workflow
id: planning-only
description: Produce a scoped plan, work breakdown, risks, and acceptance criteria without implementation.
root:
    node_key: root
    kind: root
    role_id: root_planning_lead
    policy_id: standard-root
    description: Preserve the planning-only purpose and close only when the final plan is actionable, reviewed, and clearly non-implementation.
    instruction: >-
      Keep the workflow in planning mode. Route implementation requests to a later workflow instead of silently doing them here.
    criteria:
        - slot: planning_only_criteria
          description: Hard criteria for closing planning-only work.
          criteria:
              - final plan explains objective, scope, sequencing, dependencies, risks, and acceptance criteria
              - plan names open decisions and human inputs that would change execution
              - no implementation work is performed by this workflow
    children:
        - node_key: define_scope
          kind: worker
          role_id: product_planner
          policy_id: standard-worker-human-request
          description: Define the problem, desired outcome, constraints, and scope boundary.
          instruction: >-
            Separate must-have scope, follow-up scope, out-of-scope work, and open product decisions.
          produces:
              artifacts:
                  - slot: scope_brief
                    file_hint: scope_brief.md
                    description: Problem, desired outcome, constraints, and accepted scope boundary.
        - node_key: map_work
          kind: worker
          role_id: project_manager
          policy_id: standard-worker-human-request
          description: Convert the scope brief into task slices, sequencing, dependencies, and risks.
          instruction: >-
            Keep task slices bounded and ready for later assignment. Do not implement them.
          consumes:
              artifacts:
                  - slot: scope_brief
          produces:
              artifacts:
                  - slot: work_breakdown
                    file_hint: work_breakdown.md
                    description: Work packages, sequencing, dependencies, risks, and verification gates.
        - node_key: review_plan_scope
          kind: worker
          role_id: scope_reviewer
          policy_id: standard-worker-human-request
          description: Review the plan for contradictions, missing prerequisites, and weak acceptance criteria.
          instruction: >-
            Request concrete corrections and identify decisions needed before execution.
          consumes:
              artifacts:
                  - slot: scope_brief
                  - slot: work_breakdown
              criteria:
                  - slot: planning_only_criteria
          produces:
              artifacts:
                  - slot: plan_scope_review
                    file_hint: plan_scope_review.md
                    description: Scope, feasibility, and acceptance-risk review for the plan.
        - node_key: publish_final_plan
          kind: worker
          role_id: project_manager
          policy_id: standard-worker-human-request
          description: Publish the final planning artifact from scope, work breakdown, and review evidence.
          instruction: >-
            Resolve review feedback where possible and clearly name remaining decisions or blockers.
          consumes:
              artifacts:
                  - slot: scope_brief
                  - slot: work_breakdown
                  - slot: plan_scope_review
              criteria:
                  - slot: planning_only_criteria
          produces:
              artifacts:
                  - slot: final_plan
                    file_hint: final_plan.md
                    description: Final scoped plan with task slices, risks, decisions, and acceptance criteria.
```

# MVP build workflow example

This example mirrors the shipped `mvp-build` workflow fixture.

```yaml
kind: workflow
id: mvp-build
description: Validate a real product pain and charter before planning, building, reviewing, and verifying one thin MVP story.
root:
    node_key: root
    kind: root
    role_id: root_planning_lead
    policy_id: standard-root
    description: Preserve MVP purpose and close only when charter, delivery, and validation evidence prove one real differentiated story.
    instruction: >-
      Keep the workflow waterfall-gated. Do not allow delivery planning before an authorized charter exists. Treat weak pain evidence, solved opponent gaps, or an undifferentiated story as blockers rather than reasons to build anyway.
    criteria:
        - slot: mvp_release_criteria
          description: Hard criteria for MVP closure.
          criteria:
              - authorized charter proves a real target-user pain, current alternatives or opponents, an unsolved gap, a differentiated product story, included scope, and excluded scope
              - delivery plan, setup contract, implementation, review, verification, and story validation all refer to the same authorized charter
              - runnable MVP evidence demonstrates the story's advantage and uniqueness over current alternatives
              - unresolved real-pain, differentiation, feasibility, coverage, or demo-story risk blocks closure
    children:
        - node_key: charter_phase
          kind: parent
          role_id: planning_lead
          policy_id: standard-parent
          description: Coordinate proposal construction, charter validation, refinement loops, and charter authorization before any delivery planning.
          instruction: >-
            Run proposal work before validation. If validation finds fixable gaps, assign proposal_build again with the exact missing evidence or story corrections. If research cannot prove real pain, an unsolved opponent gap, and a credible differentiated story, return blocked instead of advancing to delivery.
          criteria:
              - slot: charter_phase_criteria
                description: Hard criteria for leaving charter phase.
                criteria:
                    - proposal evidence is source-grounded and separates observed pain from guesses
                    - charter validation reviews pain, opponent gap, positioning, feasibility, and scope boundaries
                    - authorized charter defines included scope, excluded scope, proof path, and demo story before delivery planning starts
          child_defaults:
              criteria:
                  - charter_phase_criteria
          children:
              - node_key: proposal_build
                kind: parent
                role_id: planning_lead
                policy_id: standard-parent
                description: Build or refine the MVP charter proposal from product discovery, opponent gaps, and core story evidence.
                instruction: >-
                  Gather evidence first, then shape the proposal. Do not write an implementation plan. Preserve rejected opportunities, source limits, and disconfirming evidence so validation can judge the idea honestly.
                criteria:
                    - slot: proposal_build_criteria
                      description: Hard criteria for the MVP charter proposal.
                      criteria:
                          - research covers real user pain, current workarounds, current alternatives or opponents, complaints, and source confidence
                          - proposal states the core product story, why current alternatives fail, the better wedge, included MVP scope, excluded scope, and proof path
                          - proposal does not contain a delivery plan or implementation schedule
                children:
                    - node_key: product_discovery_research
                      kind: worker
                      role_id: product_discovery_researcher
                      policy_id: standard-worker
                      description: Research real user pain, current workarounds, alternatives, communities, and disconfirming evidence.
                      instruction: >-
                        Search broadly across credible public and task-provided sources. Prefer real complaints, repeated community patterns, review-site pain, forum threads, support issues, and current workaround evidence over opinions about the idea.
                      criteria:
                          - slot: product_discovery_criteria
                            description: Hard criteria for product discovery evidence.
                            criteria:
                                - evidence identifies a concrete target user and painful job from observed behavior rather than guessed demand
                                - current alternatives, workarounds, or opponents are named with strengths, failures, and complaint patterns
                                - source limits, weak signals, contradictions, and disconfirming evidence are explicit
                      produces:
                          artifacts:
                              - slot: product_discovery_report
                                file_hint: product_discovery_report.md
                                description: Source-grounded real-pain, workaround, alternative, community, and confidence evidence.
                    - node_key: opponent_gap_research
                      kind: worker
                      role_id: product_discovery_researcher
                      policy_id: standard-worker
                      description: Research why current alternatives fail and where a narrow MVP could be meaningfully better.
                      instruction: >-
                        Compare current alternatives by workflow, audience, pricing, positioning, review complaints, missing jobs, and switching friction. Look for a narrow wedge, not a generic claim that the MVP is better.
                      consumes:
                          artifacts:
                              - slot: product_discovery_report
                      produces:
                          artifacts:
                              - slot: opponent_gap_report
                                file_hint: opponent_gap_report.md
                                description: Opponent and workaround gap analysis with differentiated opportunity signals.
                    - node_key: core_story_scope_proposal
                      kind: worker
                      role_id: product_story_strategist
                      policy_id: standard-worker
                      description: Convert discovery and opponent-gap evidence into a charter proposal with core story and scope boundaries.
                      instruction: >-
                        Write a marketing-aware but evidence-bound product story. Tie target user, painful job, current alternatives, better wedge, demo proof path, included scope, and excluded scope into one charter proposal.
                      consumes:
                          artifacts:
                              - slot: product_discovery_report
                              - slot: opponent_gap_report
                          criteria:
                              - slot: product_discovery_criteria
                              - slot: proposal_build_criteria
                      produces:
                          artifacts:
                              - slot: mvp_charter_proposal
                                file_hint: mvp_charter_proposal.md
                                description: MVP charter proposal covering real pain, opponent gap, core story, proof path, included scope, and excluded scope.
              - node_key: charter_validation
                kind: parent
                role_id: planning_lead
                policy_id: standard-parent-human-request
                description: Validate the MVP charter proposal and authorize only a scope that passes real-pain, positioning, feasibility, and boundary checks.
                instruction: >-
                  Review before authorization. If validation gaps are fixable, return the exact critique to charter_phase for another proposal_build pass. If the evidence cannot prove real pain, an unsolved gap, and a differentiated story, return blocked. Use human requests only for material direction, approval, input, or review that cannot be settled from evidence.
                consumes:
                    artifacts:
                        - slot: product_discovery_report
                        - slot: opponent_gap_report
                        - slot: mvp_charter_proposal
                    criteria:
                        - slot: proposal_build_criteria
                criteria:
                    - slot: charter_validation_criteria
                      description: Hard criteria for authorizing the MVP charter.
                      criteria:
                          - validation confirms the pain is real, repeated, and important enough to justify an MVP
                          - validation confirms the core story is meaningfully different from current alternatives or opponents
                          - validation confirms included scope can demonstrate the story while excluded scope prevents speculative expansion
                          - validation fails or blocks when evidence is guessed, thin, contradicted, already solved, or not feasible to prove
                child_defaults:
                    criteria:
                        - charter_validation_criteria
                children:
                    - node_key: pain_evidence_review
                      kind: worker
                      role_id: product_reviewer
                      policy_id: standard-worker
                      description: Review whether the proposal proves real target-user pain from evidence rather than assumption.
                      instruction: >-
                        Judge source quality, repeated pain patterns, current behaviors, workaround cost, and disconfirming evidence. Do not approve guessed demand.
                      consumes:
                          artifacts:
                              - slot: product_discovery_report
                              - slot: mvp_charter_proposal
                      produces:
                          artifacts:
                              - slot: pain_evidence_review
                                file_hint: pain_evidence_review.md
                                description: Pass, fail, or gap review of real-pain evidence.
                    - node_key: story_positioning_review
                      kind: worker
                      role_id: marketing_strategist
                      policy_id: standard-worker
                      description: Review whether the product story is differentiated, marketing-aware, and grounded in opponent gaps.
                      instruction: >-
                        Judge the story against current alternatives, audience language, competitor complaints, proof points, and positioning risk. Reject generic better/faster/cheaper claims without evidence.
                      consumes:
                          artifacts:
                              - slot: opponent_gap_report
                              - slot: mvp_charter_proposal
                      produces:
                          artifacts:
                              - slot: story_positioning_review
                                file_hint: story_positioning_review.md
                                description: Positioning, differentiation, opponent-gap, and story-risk review.
                    - node_key: feasibility_scope_review
                      kind: worker
                      role_id: scope_reviewer
                      policy_id: standard-worker
                      description: Review whether the proposed included and excluded scope can prove the story without expanding into a full product.
                      instruction: >-
                        Check scope boundaries, feasibility, demo proof path, hidden dependencies, acceptance criteria, and whether the story can be shown by a thin MVP slice.
                      consumes:
                          artifacts:
                              - slot: mvp_charter_proposal
                              - slot: pain_evidence_review
                              - slot: story_positioning_review
                          criteria:
                              - slot: charter_validation_criteria
                      produces:
                          artifacts:
                              - slot: feasibility_scope_review
                                file_hint: feasibility_scope_review.md
                                description: Feasibility, scope-boundary, and proof-path review for the MVP charter.
                    - node_key: authorize_charter
                      kind: worker
                      role_id: product_reviewer
                      policy_id: standard-worker-human-request
                      description: Authorize the validated MVP charter or report the exact blocker that prevents authorization.
                      instruction: >-
                        Authorize only if pain, story, positioning, feasibility, and scope reviews pass. Ask for human approval or direction only when evidence leaves a material product decision unresolved. If the proposal cannot pass, publish blocker evidence instead of authorizing.
                      consumes:
                          artifacts:
                              - slot: mvp_charter_proposal
                              - slot: pain_evidence_review
                              - slot: story_positioning_review
                              - slot: feasibility_scope_review
                          criteria:
                              - slot: charter_validation_criteria
                      produces:
                          artifacts:
                              - slot: authorized_charter
                                file_hint: authorized_charter.md
                                description: Authorized MVP charter with final story, included scope, excluded scope, proof path, and unresolved risks.
        - node_key: delivery_phase
          kind: parent
          role_id: planning_lead
          policy_id: standard-parent
          description: Coordinate post-charter waterfall planning, setup, implementation, review, verification, and story validation.
          instruction: >-
            Start only from the authorized charter. Enforce waterfall order: plan, review plan coverage, setup contract, implement one scope, review, verify, then validate story advantage. If the plan cannot cover the charter or the built slice cannot demonstrate advantage, route correction or return blocked.
          consumes:
              artifacts:
                  - slot: authorized_charter
          criteria:
              - slot: delivery_phase_criteria
                description: Hard criteria for delivery phase.
                criteria:
                    - delivery work uses the authorized charter as the single product contract
                    - plan coverage review passes before setup or implementation starts
                    - implementation remains inside included scope and named exclusions stay untouched
                    - story validation proves the runnable slice demonstrates the authorized advantage
          child_defaults:
              criteria:
                  - delivery_phase_criteria
          children:
              - node_key: waterfall_plan
                kind: parent
                role_id: planning_lead
                policy_id: standard-parent
                description: Produce, review, and contract the delivery plan before implementation starts.
                instruction: >-
                  Convert the authorized charter into a strict waterfall delivery plan. Review coverage before setup. Do not assign implementation until the plan and setup contract prove the demo story can run and show the intended advantage.
                consumes:
                    artifacts:
                        - slot: authorized_charter
                criteria:
                    - slot: plan_coverage_criteria
                      description: Hard criteria for the MVP delivery plan.
                      criteria:
                          - plan covers every included scope item needed to run the story and excludes explicitly deferred work
                          - plan names the demo path, validation commands, acceptance checks, dependencies, setup needs, and risk gates
                          - review confirms the plan can demonstrate uniqueness and advantage over current alternatives
                children:
                    - node_key: project_plan
                      kind: worker
                      role_id: project_manager
                      policy_id: standard-worker
                      description: Convert the authorized charter into a waterfall delivery plan with demo path, dependencies, acceptance checks, and risk gates.
                      instruction: >-
                        Plan only from the authorized charter. Produce sequencing, prerequisites, one-scope implementation boundary, review and verification gates, demo path, and excluded scope.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                      produces:
                          artifacts:
                              - slot: waterfall_delivery_plan
                                file_hint: waterfall_delivery_plan.md
                                description: Waterfall delivery plan tied to the authorized charter and runnable demo story.
                    - node_key: plan_coverage_review
                      kind: worker
                      role_id: scope_reviewer
                      policy_id: standard-worker
                      description: Review the delivery plan for charter coverage, demo proof, scope control, and validation readiness.
                      instruction: >-
                        Verify that the plan covers the authorized story without overbuilding. Reject plans that cannot run the story, prove the advantage, or preserve excluded scope.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                              - slot: waterfall_delivery_plan
                          criteria:
                              - slot: plan_coverage_criteria
                      produces:
                          artifacts:
                              - slot: plan_coverage_review
                                file_hint: plan_coverage_review.md
                                description: Coverage and proof-path review for the waterfall delivery plan.
                    - node_key: setup_contract
                      kind: worker
                      role_id: project_manager
                      policy_id: standard-worker
                      description: Publish the concrete setup and implementation contract required before build work starts.
                      instruction: >-
                        Define workspace assumptions, commands, files or areas to inspect, implementation boundary, acceptance checks, validation route, and handoff requirements for the first scope.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                              - slot: waterfall_delivery_plan
                              - slot: plan_coverage_review
                          criteria:
                              - slot: plan_coverage_criteria
                      produces:
                          artifacts:
                              - slot: setup_contract
                                file_hint: setup_contract.md
                                description: Concrete setup, implementation boundary, commands, checks, and handoff contract for the MVP slice.
              - node_key: implementation
                kind: parent
                role_id: planning_lead
                policy_id: standard-parent
                description: Coordinate implementation, review, and verification for the one authorized MVP scope.
                instruction: >-
                  Assign one implementation scope at a time. Inspect child evidence before routing the next step. Do not parallelize shared code or widen beyond the setup contract.
                consumes:
                    artifacts:
                        - slot: authorized_charter
                        - slot: setup_contract
                criteria:
                    - slot: implementation_subtree_criteria
                      description: Hard criteria for the MVP implementation subtree.
                      criteria:
                          - patch implements only the setup contract and authorized included scope
                          - review evidence addresses scope creep, correctness, and risk before verification
                          - verification evidence proves the accepted behavior and names untested areas
                child_defaults:
                    criteria:
                        - implementation_subtree_criteria
                children:
                    - node_key: implement_one_scope
                      kind: worker
                      role_id: engineer
                      policy_id: standard-worker
                      description: Implement one bounded MVP scope from the authorized charter and setup contract.
                      instruction: >-
                        Read the authorized charter, delivery plan, plan review, and setup contract before editing. Keep the patch thin and publish residual risks instead of widening scope.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                              - slot: waterfall_delivery_plan
                              - slot: plan_coverage_review
                              - slot: setup_contract
                      produces:
                          artifacts:
                              - slot: scope_patch
                                file_hint: scope_patch.diff
                                description: Patch for the one authorized MVP implementation scope.
                    - node_key: review_scope
                      kind: worker
                      role_id: code_reviewer
                      policy_id: standard-worker
                      description: Review the MVP scope patch against charter, setup contract, correctness, and scope boundaries.
                      instruction: >-
                        Focus on correctness, regression risk, missing tests, implementation fit, and whether the patch stayed inside the authorized MVP scope.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                              - slot: setup_contract
                              - slot: scope_patch
                          criteria:
                              - slot: implementation_subtree_criteria
                      produces:
                          artifacts:
                              - slot: scope_review
                                file_hint: scope_review.md
                                description: Code review findings for the MVP scope patch.
                    - node_key: verify_scope
                      kind: worker
                      role_id: test_verifier
                      policy_id: standard-worker-command-run
                      description: Verify the MVP scope behavior, acceptance checks, and runnable demo path.
                      instruction: >-
                        Verify the smallest evidence set that proves accepted behavior and demo readiness. Use command runs only for long or log-heavy checks.
                      consumes:
                          artifacts:
                              - slot: authorized_charter
                              - slot: setup_contract
                              - slot: scope_patch
                              - slot: scope_review
                          criteria:
                              - slot: implementation_subtree_criteria
                      produces:
                          artifacts:
                              - slot: scope_verification_report
                                file_hint: scope_verification_report.md
                                description: Verification evidence for accepted MVP behavior and demo readiness.
              - node_key: validate_story_advantage
                kind: worker
                role_id: product_reviewer
                policy_id: standard-worker-human-request
                description: Validate that the built MVP slice can run the authorized story and demonstrate real advantage over current alternatives.
                instruction: >-
                  Judge the runnable story against the authorized charter, opponent gap, delivery plan, patch, review, and verification evidence. Treat weak uniqueness, unproven advantage, or failed demo path as a blocker. Ask for human review only when the evidence leaves a material product judgment unresolved.
                consumes:
                    artifacts:
                        - slot: authorized_charter
                        - slot: opponent_gap_report
                        - slot: waterfall_delivery_plan
                        - slot: scope_patch
                        - slot: scope_review
                        - slot: scope_verification_report
                    criteria:
                        - slot: delivery_phase_criteria
                        - slot: mvp_release_criteria
                produces:
                    artifacts:
                        - slot: story_advantage_validation
                          file_hint: story_advantage_validation.md
                          description: Product validation that the runnable MVP story demonstrates the intended advantage and uniqueness.
        - node_key: release_closure
          kind: worker
          role_id: release_operator
          policy_id: standard-worker
          description: Close the MVP build from authorized charter, delivery, review, verification, and story-validation evidence.
          instruction: >-
            Use only surfaced MVP evidence and release criteria. Do not reopen research, planning, or implementation. Report release gaps or blockers instead of converting weak evidence into success.
          consumes:
              artifacts:
                  - slot: authorized_charter
                  - slot: waterfall_delivery_plan
                  - slot: setup_contract
                  - slot: scope_patch
                  - slot: scope_review
                  - slot: scope_verification_report
                  - slot: story_advantage_validation
              criteria:
                  - slot: mvp_release_criteria
          produces:
              artifacts:
                  - slot: closure_report
                    file_hint: closure_report.md
                    description: Final MVP release or blocked-closure report from charter, delivery, and validation evidence.
```

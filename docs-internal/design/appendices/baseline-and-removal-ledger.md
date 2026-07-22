# AutoClaw baseline and Banksia removal ledger

Status: Reference

This ledger protects the controller properties that Banksia must retain while its public and runtime model changes. It records the AutoClaw 0.1.8 baseline at Git commit `2ff6e0fbe2f469ee1ce394bc477a688327680c8c`. Paths and tests in the current-owner columns are migration evidence, not Banksia naming or layout targets.

WP-00 changes no runtime writer or reader. A later package may replace a test only when target-equivalent proof lands in the same change and this ledger's deletion owner is satisfied.

## Preserved controller invariants

| Invariant | Current implementation owner | Direct current proof | Banksia replacement owner |
| --- | --- | --- | --- |
| Immutable published definition revisions and exact Task launch pinning | `apps/api/src/autoclaw/definitions/registry/revisions/`, `definitions/registry/task_start.py`, `runtime/launch/service.py`, and `persistence/models/registry.py` | `definition_registry/test_launch_snapshot.py::test_launch_snapshot_pins_current_registry_workflow_role_and_policy_revisions`; `definition_registry/test_concurrency.py::test_concurrent_new_key_upserts_create_ordered_revisions` | WP-02 owns Workflow-only revisions and publication; WP-03 owns target Task start and exact revision pinning. |
| Assignment, Attempt, Dispatch, predecessor, and exact-source identity lineage | `persistence/models/runtime/assignment/execution.py`, `persistence/models/runtime/dispatch/`, `persistence/models/runtime/flow/`, `runtime/boundary/`, and `runtime/launch/` | `runtime_schema_contract/test_guard.py::test_boundary_successor_must_name_the_source_dispatch_as_predecessor`; `runtime/boundary/test_source_transitions.py::test_child_terminal_boundary_routes_exact_parent_before_success` | WP-03 preserves Assignment/Attempt/Checkpoint lineage; WP-07 moves currentness and sources to Attempt lanes; WP-08 adds Wave-member sources. |
| One database-backed current-authority predicate per execution lane | `persistence/models/runtime/flow/runtime.py`, `runtime/dispatch/authority.py`, and `runtime/flow/current_sources.py` | `runtime_schema_contract/test_current_dispatch_constraints.py`; `runtime_schema_contract/test_provider_start_acceptance.py::test_concurrent_successor_candidates_commit_one_current_dispatch` | WP-07 replaces the Flow-wide predicate with Attempt-local current Dispatch XOR typed wait and proves one-lane parity before deletion. |
| Immutable exact Dispatch request and byte-stable same-Dispatch retry | `runtime/dispatch/request_pair.py`, `runtime/dispatch/prompt_snapshot.py`, `runtime/dispatch/provider_start.py`, and Dispatch support models | `unit/runtime/dispatch/test_request_pair.py::test_request_pair_publishes_complete_immutable_bytes_and_logical_refs`; `integration/runtime/providers/test_starter.py::test_startup_recovery_stops_and_rotates_before_retrying_same_dispatch` | WP-05 moves exact strings into immutable `DispatchRequest` truth and adapters; WP-07 preserves same-Dispatch provider-start retry. |
| Controller intent commits before provider, process, or other external effects | `runtime/dispatch/opening.py`, `runtime/post_commit/router.py`, `runtime/human_request/service.py`, and `runtime/command_run/service.py` | `definition_registry/test_launch_snapshot.py::test_task_start_publishes_exact_follow_on_only_after_sqlite_commit`; `runtime/node_operations/test_follow_on_publication.py::test_human_request_publishes_only_exact_open_signal_after_commit`; `test_command_run_commit_survives_runtime_publication_exception` | WP-03 and WP-05 preserve start/Checkpoint/Dispatch ordering; WP-07 owns external-wait continuation and post-commit effects. |
| Disposable duplicate/lost signals converge from committed natural sources | `runtime/post_commit/router.py`, `runtime/startup_audit.py`, exact-source continuation owners, and provider starter | `runtime/boundary/test_continuation.py::test_exact_yield_source_opens_one_child_dispatch_and_duplicate_loses`; `runtime/projection/test_support_projection_owner.py::test_startup_pages_and_republishes_all_six_exact_source_families` | Preserved through WP-05 and WP-07; WP-08 adds Wave settlement and continuation hints under the same reread-and-no-op rule. |
| Provider-start reservation, retry, and startup convergence keep the same Dispatch authoritative | `runtime/dispatch/provider_start.py`, `runtime/providers/`, managed binding registry, and `runtime/startup_audit.py` | `runtime_schema_contract/test_provider_start_acceptance.py`; `runtime/providers/test_starter.py::test_startup_recovery_stops_and_rotates_before_retrying_same_dispatch`; `mcp/node_server/test_managed_authority.py::test_retry_binding_uses_a_fresh_credential_for_the_same_dispatch` | WP-07 migrates binding/currentness to Attempt scope; WP-08 proves multiple independent lanes without weakening retry or recovery. |
| Watchdog replacement has one winner, preserves same-Assignment semantics, and handles ownership loss explicitly | `runtime/watchdog/`, `runtime/dispatch/provider_start.py`, `runtime/command_run/ownership_recovery.py`, and `runtime/startup_audit.py` | `runtime/watchdog/test_recovery.py::test_watchdog_replaces_one_stale_dispatch_and_duplicate_signal_loses`; `test_wait_open_and_watchdog_have_one_commit_order_winner`; `runtime/command_run/test_process_owner.py::test_startup_running_command_routes_to_ownership_loss_recovery` | WP-07 owns Attempt-local watchdog and typed external waits; WP-08 proves watchdog interaction with nested concurrent lanes. |
| Human Request and Command Run waits are typed, exact-source, durable, and resumed once | `persistence/models/runtime/waiting.py`, `human_requests.py`, `command_runs.py`, `runtime/human_request/`, and `runtime/command_run/` | `runtime/node_operations/test_external_wait_operations.py::test_human_request_open_persists_typed_source_and_exact_wait`; `runtime/human_request/test_human_continuation.py::test_terminal_human_source_opens_one_same_attempt_successor`; `runtime/command_run/test_command_continuation.py::test_terminal_command_source_opens_one_same_attempt_successor` | WP-05 simplifies the public operation shapes; WP-07 migrates waits and continuation to the owning Attempt. |
| Checkpoints are durable exact-execution reports and terminal boundaries commit atomically | `runtime/checkpoint/`, `runtime/boundary/`, `persistence/models/runtime/assignment/execution.py`, and boundary contracts | `runtime/node_operations/test_checkpoint_and_boundary.py::test_record_checkpoint_persists_exact_source_and_keeps_dispatch_open`; `test_return_blocked_boundary_closes_exact_source_after_prerequisites`; `runtime/boundary/test_source_transitions.py::test_worker_retry_creates_one_attempt_and_consumes_budget_atomically` | WP-03 introduces one `checkpoint` action while retaining progress plus terminal green, blocked, and retry AcceptedBoundary semantics. |
| Terminal truth is selected through an exact relationship, never latest timestamp or provider output | Attempt latest-Checkpoint pointer, Assignment decision and accepted-boundary relations in runtime persistence and release services | `runtime_schema_contract/test_controller_contracts.py::test_attempt_latest_checkpoint_pointer_accepts_only_the_exact_attempt`; `runtime/node_operations/test_release_operations.py::test_release_green_uses_exact_attempt_checkpoint_pointer`; `test_release_decision_freezes_checkpoint_evidence` | WP-03 makes the accepted root green/blocked Checkpoint the exact Result and removes duplicate release/result prose only after relation proof. |
| Ordered generic file-reference values belong to their owning message and remain honest about mutable bytes | No target-equivalent current owner. Current Artifact publication, transient localization, and path-only claim machinery are migration evidence, not a green invariant. | Current `test_checkpoint_publication.py` and child-assignment Artifact tests characterize the old shape only; they must not be promoted as generic `FileReference` proof. | WP-03 lands owner-scoped path/description values and removes the Artifact resource domain; WP-04 adds physical workspace validation and mutable/missing-file proof. |
| Structural changes use immutable revision history, candidate validation, and compare-and-swap currentness | `runtime/node_operations/structural_revisions.py`, `structural_candidate/`, structural handlers, and Flow graph models | `runtime/node_operations/test_structural_revisions.py::test_add_update_remove_rebuilds_relational_tree_and_exact_edges`; `test_open_work_and_stale_expected_revision_reject_without_orphans`; `test_non_root_owner_cannot_cross_relational_subtree`; `test_revision_races.py::test_structural_adoption_and_terminal_checkpoint_have_one_winner` | WP-06 replaces the public replan contract while preserving immutable TeamRevision history, caller-bounded authority, busy guards, and one-winner CAS. |
| Pause, resume, cancel, and recovery enumerate and control all current work without fabricating completion | `runtime/flow/control.py`, `runtime/flow/continuation.py`, cancellation, current-source readers, external-wait owners, and startup audit | `runtime/flow/test_flow_controls.py::test_pause_closes_exact_current_dispatch_and_rejects_stale_control`; `test_cancel_wins_over_stale_continue_without_opening_a_successor`; `runtime/flow/test_operator_continuation.py::test_continue_resumes_one_closed_lineage_tail_and_rejects_duplicate`; `e2e/workflows/test_wait_watchdog_recovery.py` | WP-07 migrates controls to all Attempt lanes; WP-09 maps them to Task product services after Flow contraction. |
| Raw audit chronology remains exact and separate from human product Activity | `runtime/task_events.py`, task-event persistence/contracts, HTTP event transport, and the legacy Console's partial milestone classifier | `runtime_schema_contract/test_task_events.py::test_concurrent_appends_commit_one_strict_sequence_and_hash_chain`; `test_task_event_reads_resume_exclusively_and_stop_at_high_water_mark`; `public_surfaces/http/test_task_event_transport.py::test_task_event_http_and_sse_preserve_cursor_contract` | WP-09 retains raw support/audit chronology and introduces backend-owned semantic TaskActivity/TaskView. The current frontend classifier is contrast, not the target owner. |

The two target deltas in the table—generic `FileReference` and backend-owned semantic Activity—do not justify WP-00 characterization tests. Encoding the legacy Artifact resource or frontend event classifier as desired behavior would preserve the wrong contract.

## Reader and writer removal map

| Current family | Target replacement | Old readers and writers leave by |
| --- | --- | --- |
| AutoClaw import, CLI, environment, service, config, DB, package, and built-in server identity | Banksia identity only, with reset state and no fallback alias | WP-01 establishes behavior-neutral identity; WP-12 and WP-13 prove no residual identity or package path. |
| Role, Policy, generic Definition registry/search, and generic seed mirroring | One Workflow-specific draft/publication/revision catalog and separate Starter Workflow seed inventory | WP-02; the current Role/Policy seed-mirror validator remains baseline proof until that package replaces it. |
| Definition compiler and CompiledPlan dependency graph | Workflow normalization/validation and initial Task-team materialization | WP-02 introduces the seam; WP-09 removes residual compiler/registry ownership. |
| Persisted Task Compose, preview, key/title/summary/instruction quartet | Transient `TaskStartRequest` and one exact Assignment prompt | WP-03. |
| Assignment criteria, consume, produce, evidence, release-basis, and slot contracts | Complete prompt, optional file references, participation, and accountable Checkpoint | WP-03, with physical path behavior completed in WP-04. |
| Separate progress Checkpoint, `return_boundary`, release-green/release-blocked, and duplicate final prose | One `checkpoint` action with progress or terminal green/blocked/retry and exact root Result | WP-03; temporary child-yield transfer remains only until WP-08. |
| Artifact publication/body/capture/version/current-pointer and transient resource families | Loose workspace files plus owner-scoped ordered `{path, description?}` values | WP-03 deletes the resource domain; WP-04 proves native workspace and file behavior; WP-13 rechecks absence. |
| Human Request context refs and suggested instruction | Typed request with optional generic file references and conditional system-prompt teaching | WP-05, after owning file values land in WP-03/04. |
| Command Run environment/expected-output refs and split output | Controller-approved environment, simple request, one combined protected/visible log | WP-04 owns output; WP-05 owns operation/Continuation shape. |
| Task-root abstraction, many runtime projections, request files, and Node list/read/note tools | Shared workspace with physical `.banksia/`, two projections, loose notes/artifacts, exact DB request strings, and native provider filesystem access | WP-04 establishes the workspace; WP-05 removes request files and controller file tools after equivalence proof. |
| Direct-child-only structural schemas and model-visible expected revision | Caller-bounded recursive add/update/remove with controller IDs and private CAS | WP-06. |
| Flow-wide current Dispatch/wait and one live execution slot | Attempt-local current Dispatch XOR typed wait | WP-07, followed by residual Flow contraction in WP-09. |
| Staged single-child `assign_child` plus `yield` | Atomic one-to-eight-member Delegation Wave and local collect-all join | WP-08; one-member parity must land before the final cutover removes both old operations. |
| Raw TaskEvent feed and Flow/runtime product payloads | Semantic TaskView, TaskActivity, attention, legal actions, Result, and separate support/audit API | WP-09. |
| Legacy `apps/console` | Fresh root React/Tailwind Workflow and Run Studios plus separate Operator | WP-10 and WP-11 build the replacement; WP-12 deletes the old app. |
| Versioned AutoClaw public/internal docs and obsolete ADRs | Versionless shipped Banksia documentation and only still-governing decisions | WP-12; WP-13 performs the final target-to-owner audit. |

## Characterized command baseline

The pre-edit WP-00 matrix produced these results on 2026-07-23:

| Command | Result |
| --- | --- |
| `make check-api` | Passed. |
| `make test-api` | 555 passed, 2 failed, with 5,014 Python 3.14/pytest-asyncio deprecation warnings. |
| `make test-api-integration` | 431 passed, 2 skipped. |
| `make test-api-db` | 181 passed, 1 skipped, 6 failed against real PostgreSQL; the harness cleaned its container, network, and volume. |
| `make test-api-e2e-bounded` | 1 passed. |
| `make test-api-e2e-reviewed` | 1 passed. |
| `make test-api-e2e-staged` | 1 passed. |
| `make check-console` | Passed: 52 unit/component tests, 63 integration tests, generated-contract checks, and production build; one nonfatal build warning remained. |
| `make console-e2e` | 31 passed, 8 failed, 17 skipped. |
| `make check-docs` | Passed. |

### Backend unit exceptions

These are characterized failures, not WP-00 regressions:

1. `apps/api/tests/unit/runtime/test_launch_bootstrap.py::test_launch_service_derives_initial_ids_from_nonliteral_root_key` uses an obsolete fake DB session. WP-03 replaces the Task-start path.
2. `apps/api/tests/unit/style_audit/test_loader_and_layout.py::test_build_audit_settings_exposes_phase6_wrapper_and_direction_scopes` expects a stale AutoClaw/OpenClaw naming exception. WP-01 owns the identity correction.

The 5,014 warnings are baseline migration debt rather than authority-document work. Their removal is required before final release proof, with the owning code packages responsible when they touch the affected async test surfaces.

### PostgreSQL exceptions

The six failures are pre-existing Flow-era schema reflection and cross-owner guard gaps. They remain required comparison points and must become green after their WP-02/WP-03/WP-07 replacements:

1. `test_postgresql_reflects_and_enforces_current_dispatch_constraints`;
2. `test_flow_start_source_cannot_consume_another_flows_root`;
3. `test_dispatch_node_must_belong_to_its_assignment`;
4. `test_readyz_uses_real_database`;
5. `test_lifespan_fails_closed_on_stale_runtime_schema`; and
6. `test_lifespan_creates_schema_only_for_genuinely_empty_database`.

### Legacy Console browser exceptions

The eight failures are stale copy or locator expectations in the disposable legacy Console and are replacement-owned by WP-10/WP-11:

1. Chromium — `console-shell.spec.ts`: “keeps the shell keyboard path visible”;
2. Mobile Chrome — the same shell keyboard-path case;
3. Chromium — `definition-editor.spec.ts`: “keeps the Definition Editor workbench stable with no saved drafts”;
4. Chromium — `definitions.spec.ts`: “renders Definitions browse detail, versions, focus, and accessibility at desktop width”;
5. Chromium — `task-detail.spec.ts`: “renders the API-backed Task Detail control room at desktop width”;
6. Mobile Chrome — `task-detail.spec.ts`: “keeps the Task Detail graph and event lane responsive at mobile width”;
7. Chromium — `task-start.spec.ts`: “starts a task from stored workflow truth at desktop width”; and
8. Mobile Chrome — `task-start.spec.ts`: “keeps Task Start root modes, validation, and layout usable at mobile width”.

WP-00 may carry only these reproduced exceptions. Any additional failure is a new regression until its exact cause and owner are established.

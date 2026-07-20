# Prompt system

Status: Target

This page owns the exact V2 model-visible instruction and input request for one dispatch. Controller state remains authoritative for currentness and legality; the two immutable request files are authoritative only for the bytes delivered for that dispatch.

## Request identity

Every dispatch owns exactly two immutable task-relative files:

```text
_runtime/dispatch/<dispatch_id>/instructions.md
_runtime/dispatch/<dispatch_id>/input.md
```

The database owns one one-to-one refs-only record:

```yaml
dispatch_prompt_refs:
  dispatch_id: <canonical dispatch id>
  instructions_logical_path: <task-relative path>
  input_logical_path: <task-relative path>
  dynamic_input_version: <integer audit label>
  created_at: <controller timestamp>
```

The row stores no prompt text, content hash, static version, catalog version, renderer version, credential, provider session, or physical filesystem path.

`dynamic_input_version` labels the schema used for newly rendered input. It is audit and migration metadata, never a provider-start or retry compatibility gate.

## Build and commit order

The exact-source dispatch-opening handler:

1. reads the committed source and minimum current controller rows;
2. builds one typed prompt-safe snapshot;
3. renders `instructions.md` and `input.md` once;
4. stages and publishes the pair so a committed ref cannot point to half a request;
5. revalidates source/currentness in one short transaction;
6. creates D2 in `starting` and its refs-only record; and
7. commits before publishing `DispatchStartDue` or performing provider I/O.

A competing opener may publish files and lose the final conditional write. The loser creates no successor and performs no provider I/O. Its unreferenced files are cleanup candidates and have no controller authority.

Watchdog uses the same preparation order, but its final transaction also atomically closes D1 and creates D2. There is no separate prompt-ready state, reservation, signal, polling loop, or acknowledgement.

## Provider delivery and retry

Provider start opens the two paths from the committed refs row and sends those exact bytes. It does not invoke the renderer, repair or substitute a file, combine the lanes, or compare content/version hashes.

A retry of the same dispatch rereads the same two files. A replacement dispatch gets a new identity and a newly rendered pair from its exact committed source.

If either committed file is missing, unreadable, outside the task resolver, or otherwise invalid, provider start performs zero provider I/O, closes the still-current starting dispatch, and pauses with `runtime_transition_failed`. Provider output, final response, EOF, drain, stop, and continuity state never modify request truth.

## Instruction assets

Keep five small authored instruction assets with one responsibility each:

```text
instructions/
  shared/
    authority.md
    context-access.md
    control-transfer.md
  families/
    worker.md
    parent-root.md
```

- `authority.md` teaches controller truth, evidence, currentness, and provider non-authority.
- `context-access.md` teaches `get_current_context` and bounded logical refs.
- `control-transfer.md` teaches checkpoints, waits, boundaries, and the rule to stop the current outer response after a successful boundary.
- `worker.md` teaches bounded execution, verification, artifact publication, and return posture.
- `parent-root.md` teaches decomposition, delegation, child-evidence review, integration, routing, and release posture.

Resolved workflow, role, node, and policy guidance follows these assets in stable order. It may narrow behavior and tools but cannot widen controller authority.

The code-owned family mapping is not a persisted version catalog or provider compatibility gate.

## Dynamic input responsibilities

The input snapshot has six purpose-first responsibilities:

| Order | Key | Question |
| ---: | --- | --- |
| 1 | `assignment` | What outcome does this node own? |
| 2 | `trigger` | Why does this turn exist, and what exact result changed? |
| 3 | `plan` | What is the complete current intended approach? |
| 4 | `context` | Which resources, restrictions, actions, and refs matter now? |
| 5 | `dispatch` | Which full controller lineage does this request describe? |
| 6 | `next` | What current read and trigger-specific decision comes next? |

These are rendering responsibilities, not tables, API calls, files, or independently persisted sections.

Every dispatch receives a complete self-orienting input. Provider history may improve quality but never permits a compact continuation, resume append, missing request lane, or message-free probe.

## Assignment section

`assignment` renders the complete current assignment purpose, criteria, declared consume/produce slots, relevant budget, and role. It does not include parent/root controller operations in a worker request.

## Trigger section

`trigger` is a strict discriminated variant selected from one exact committed source. Variants cover initial/root start, accepted boundary continuation, child return, human-request result, command-run result, watchdog recovery, semantic retry, and operator continue.

The renderer never infers a trigger from latest timestamps, filenames, provider output, task status, or nearby rows.

For child return, the child assignment, attempt, source dispatch, accepted boundary, and matching terminal checkpoint must form one identity-bound source. The prompt-safe checkpoint appears once under the trigger; child refs are not duplicated in generic context.

## Plan section

`plan` renders the complete assignment-owned work plan or explicit `null`. Plans are optional and advisory. The request does not manufacture a plan, treat completed steps as success, or omit context because a plan exists.

## Context section

`context` renders only prompt-safe controller read models:

- effective capabilities and allowed actions;
- workflow neighborhood needed for the next decision;
- exact logical readback refs for this dispatch's `instructions.md` and `input.md`, plus the workflow manifest support projection;
- consume/produce slots and rich logical refs;
- controller-selected `checkpoint_to_resume_from` when applicable;
- relevant constraints and bounded budget facts; and
- current `provider_native_access` and `network_access` effective values plus each controlling source, without credentials or provider configuration.

The two capability disclosures use the controller readback vocabulary `effective` and `source`, with source `default | policy_definition | task_policy | controller`. They remain independent axes; the prompt renderer does not infer one from the other or derive either value from provider selection.

Rich refs may include kind, logical path, purpose, description, slot, and version where applicable. The renderer does not open artifact bodies, raw command logs, ORM objects, support projections, physical roots, environment values, or secrets.

`readback_refs.instructions` and `readback_refs.input` intentionally name the two files being delivered. This path-only self-reference does not rerender or embed either file. `readback_refs.workflow_manifest` names a readable support projection that may be missing or stale; the live workflow neighborhood and controller operations remain authoritative.

## Dispatch section

`dispatch` always renders the full canonical `task_id`, `dispatch_id`, assignment ID, attempt ID, node key, and lineage needed for orientation. It has no shortened dispatch tag, combined node-dispatch alias, session key, bearer credential, provider thread ID, or MCP protocol session ID.

Public IDs orient the model; they do not authenticate managed Node MCP calls.

## Next section

`next` teaches the immediate source-specific action: obtain one coherent current context, inspect a named checkpoint/ref, resume after a human or command result, review a child return, or perform bounded assigned work.

It does not teach polling, provider-output completion, generic latest-row discovery, hidden continuation, or manual MCP lifecycle management.

## Current context relationship

The immutable input describes complete dispatch-start truth. `get_current_context()` owns current truth at call time and returns the current assignment, typed compact trigger, plan or `null`, live workflow neighborhood, capabilities, allowed actions, and bounded logical refs. It returns an exact boundary-selected checkpoint path when one applies and otherwise leaves the optional checkpoint field `null`; normalized `continuation` remains reserved and `null`. Callers read the immutable `input` ref when they need the complete dispatch-start trigger or resume payload. The response repeats the three readback refs so recovery does not depend on remembered prompt text. Its capability snapshot includes the exact `provider_native_access` and `network_access` effective/source objects.

The current-context result is not a lease. Every later operation revalidates live dispatch authority.

## Tool exposure

Prompt teaching and provider tool exposure use the same logical Node operation catalog.

- worker requests omit parent/root operations;
- parent/root requests include only policy-allowed structural operations;
- managed schemas contain semantic arguments only;
- compatibility schemas add full task/dispatch selectors; and
- provider-side allowlists narrow exposure but never replace server authorization.

The prompt does not list tools that the dispatch cannot discover through its managed binding or compatibility profile.

## Provider continuity

Provider conversation/thread/session identity is optional transport context owned by the adapter. It never proves controller currentness, request compatibility, assignment success, or permission to omit either request file.

AutoClaw ignores provider final output for correctness and never waits for a drain or terminal response before constructing a successor request.

## Required proof

- every committed dispatch has exactly one refs row and one immutable request pair;
- no committed ref points to a half-published pair;
- losing candidates leave at most unreferenced files and cause no provider I/O;
- provider start sends exactly the committed bytes;
- same-dispatch retry never rerenders;
- missing or escaped files cause zero provider calls;
- all six responsibilities render for worker, parent/root, child return, waits, recovery, retry, and continue;
- dispatch input and current context disclose both independent capability values and controlling sources;
- dispatch input and current context disclose the exact request-pair readbacks and support-only workflow-manifest readback;
- current context rereads the direct-child workflow neighborhood from controller rows;
- full canonical dispatch identity renders without credentials or aliases;
- tool teaching matches the role-specific operation ceiling; and
- request files contain no secret, private handle, physical root, raw log, or provider configuration.

## Removed target concepts

- combined `prompt.md` or `prompt-request.json` request authority;
- prompt text or hashes in the database;
- prompt-ready state machines and materialization polling;
- compact continuation, resume append, drain gate, or provider-context compatibility matrix;
- launch-time renderer or hash/version gate;
- short dispatch aliases and model-visible session keys; and
- one undifferentiated tool profile for worker and parent/root.

## Related

- [Task root and file access](../architecture/task-root-and-file-access.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Work plan and checkpoint contract](../architecture/work-plan-and-checkpoint-contract.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
- [Node and Operator MCP surface contract](../interfaces/node-and-operator-mcp-surface-contract.md)

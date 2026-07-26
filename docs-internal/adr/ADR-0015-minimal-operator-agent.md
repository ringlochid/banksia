# ADR-0015: Minimal Operator agent

Status: Accepted

## Decision summary

Banksia implements Operator as one small, separate provider-backed agent over existing product services. Claude and Codex are supported adapters. Each turn receives the same seventeen Banksia product operations and returns one provider-native typed `message | ask_user` result.

Operator is not a second Task runtime. It has two durable record types, six product routes, one active-turn compare-and-swap, and no invocation queue, effect journal, proposal/confirmation protocol, retry route, `operator_return` tool, or open provider call while a person answers a question.

## Context

The superseded Operator contract tried to create recoverable execution and effect authority around an assistant conversation. It consequently reproduced runtime machinery beside the Task runtime: queued invocations, claims, provider-call identities, effect records, confirmations, and retry coordination.

Operator needs a much smaller boundary. It helps a person author and operate Banksia through already-authoritative Workflow, Task, Human Request, and Command Run services. Those services already own ETags, Undo receipts, opaque legal-action IDs, validation, and accepted results.

The pinned Claude and Codex SDKs both support typed turn results and controller-supplied product operations. Current pinned Codex model metadata can require code mode without exposing a public Direct-mode override. Banksia therefore permits provider-native `exec` and `wait` only as isolated adapter-private transport over the exact seventeen Banksia operations plus inert `update_plan`. The code runtime receives no execution environment, host bindings, filesystem, shell, network, external MCP, module imports, Skills, or Plugins. These surfaces add no Banksia or host authority. Banksia freezes its own seventeen-operation catalog without claiming a literal global model-visible tool count.

## Decision

- Operator is conceptually one configured agent:

  ```text
  Agent(name="Operator", instructions=operator_prompt, tools=operator_tools)
  ```

- Controller configuration selects `claude` or `codex`, with optional provider-specific model and effort. Operator never inherits a Workflow Member provider and never silently falls back.
- Every turn returns one provider-native structured variant: a human-facing message or a small `ask_user` question set. `ask_user` is a result variant, not a tool. The provider invocation ends before the user answers.
- Claude uses its native structured-output path. Codex uses `outputSchema` and `dynamicTools`. A private in-process MCP projection is permitted only when an adapter needs that transport; it is not public, static, authorable, or externally configurable.
- When Codex model metadata requires code mode, `exec` and `wait` may compose only the exact seventeen Banksia operations plus inert `update_plan`. Operator supplies an empty execution-environment list, empty runtime workspace roots, a temporary cwd, and no host or extension surface. A wider nested registry or any filesystem, shell, network, external MCP, module, Skill, or Plugin access fails Operator availability.
- The Banksia catalog remains exactly seventeen typed leaf operations over existing product services. `workflow_draft_create` accepts one complete structured JSON Workflow candidate and creates or opens its mutable draft through the existing authoring services. No import or generic execution tool is added.
- Explicit user text or a committed typed answer supplies intent for the action it clearly requests. Product-service ETags, Undo receipts, current opaque legal-action IDs, and validation own currentness and acceptance. Operator does not create a parallel proposal or effect authority.
- Conversation durability uses only `OperatorConversation` and ordered `OperatorConversationEntry` records. A nullable active-turn identity is the sole turn-exclusion compare-and-swap.
- Product HTTP has six routes: status, conversation list, conversation create, conversation read, message submit, and question-answer submit. Message and answer routes run one provider turn synchronously and return committed readback.
- A provider/tool/controller interruption creates one bounded visible entry, releases the active turn, and refetches owning controller truth when the affected resource is known. Neither restart nor client retry automatically replays a provider turn or mutation.

## Consequences

- Operator stays a product assistant rather than becoming another scheduler or authority model.
- Ordinary mutation safety remains with the services that already own the resource.
- A failed turn may require a new explicit user message. Banksia preserves the visible interruption and current product truth instead of promising transparent replay.
- Provider adapters may differ in harmless native presentation surfaces while exposing the same Banksia operations and typed result contract.

## Alternatives rejected

### Keep the superseded invocation and effect wrapper

Rejected because it duplicates Task-runtime coordination without adding product authority that the owning services do not already have.

### Add an `ask_user` or `operator_return` tool

Rejected because both are provider-turn output, not product operations. Provider-native typed output keeps the turn boundary simpler.

### Put Operator on Task runtime records

Rejected because Operator is product control-plane help, not work performed by a Workflow Member.

### Expose a public Operator MCP server

Rejected because HTTP owns browser product access and provider tool transport is an adapter-private implementation detail.

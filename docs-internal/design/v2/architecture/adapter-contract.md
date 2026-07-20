# Minimal provider adapter contract

Status: Target

This page owns the smallest provider-control boundary needed by the V2 controller. Adapters start one committed dispatch, optionally stop an execution, hold provider-private resources, and expose bounded diagnostics. They do not own controller currentness, semantic completion, prompt rendering, Node operations, or runtime orchestration.

## Portable interface

Conceptually, a managed adapter implements:

```text
start(DispatchStartRequest) -> StartAccepted
stop(dispatch_id) -> Stopped | NotRunning
check() -> ProviderCheckResult
```

`stop` is optional for an experimental or limited provider route. A supported managed route should implement it when the provider offers a real cancellation boundary.

The adapter may hold private SDK clients, process handles, provider thread/session IDs, cancellation tokens, or transport state. Those details never become controller authority or generic runtime records.

## DispatchStartRequest

The runtime constructs the request only from a committed current `starting` dispatch and validated request refs:

```yaml
DispatchStartRequest:
  task_id: <canonical task id>
  dispatch_id: <canonical dispatch id>
  provider_route: <committed discriminated route>
  workspace: <resolved provider workspace/cwd>
  instructions: <exact bytes from instructions.md>
  input: <exact bytes from input.md>
  managed_node_mcp: <private connection or null>
  compatibility_node_mcp: <provider-visible connection or null>
  enabled_native_tools: <resolved provider-native access>
  continuity_hint: <optional provider-private hint>
```

The two request lanes stay separate. The adapter does not render, concatenate, repair, substitute, or persist them.

`managed_node_mcp` contains the private internal URL, opaque bearer credential, and exact dispatch tool allowlist. It is process-local and must not enter logs, task files, provider persistent config, public readbacks, or continuity fields.

OpenClaw receives the user-configured compatibility endpoint instead of a managed binding. Its tools require full task/dispatch selectors.

## Start acceptance

`StartAccepted` means the adapter accepted responsibility for the provider invocation. It is sufficient for the controller to move a still-current dispatch from `starting` to `open` and set `adapter_started_at`.

It does not mean:

- assignment success;
- provider response completion;
- first Node MCP callback;
- semantic progress;
- boundary acceptance;
- provider process longevity; or
- exactly-once external execution.

The adapter returns only bounded non-secret acceptance metadata needed for diagnostics. Provider thread/session/run identifiers may remain private continuity hints but never authenticate Node MCP or appear in generic controller state.

## Start failures and retry classification

Adapter failures normalize to stable categories such as configuration, authentication, connection, unavailable, timeout, rejected, unsupported, and unknown/uncertain acceptance.

All provider-origin start failures are retriable on the same `starting` dispatch. The generic runtime applies the configured unbounded capped backoff and records only sanitized code/readback.

The adapter must distinguish when reasonably possible:

- `definite_failure`: no provider execution was accepted; and
- `uncertain_acceptance`: an execution may have been accepted or the controller could not confirm the result.

After uncertain acceptance, the runtime revokes the prior managed binding, calls `stop(dispatch_id)` once when available, then retries the same dispatch. A route that cannot provide reliable stop/idempotency accepts the risk of duplicate physical provider work; current binding and dispatch admission still protect controller truth.

Deterministic controller-side request/ref validation does not call the adapter and is not classified as a provider failure.

## Stop contract

A successful `stop(dispatch_id)` return is proof that the adapter's execution for that dispatch is stopped or was already absent. It must include provider-owned background activity covered by that invocation, not merely close a client stream while work continues.

The call is bounded by adapter/provider policy. It does not expose a long-lived controller fence or require polling until provider output ends.

Unsupported, failed, or timed-out stop is a normalized adapter result/exception. Runtime behavior is:

- uncertain same-dispatch retry proceeds after the one attempt;
- watchdog replacement D2 starts after the one attempt against D1;
- normal boundary and legal human/command waits never call stop; and
- pause/cancel cleanup is best effort after controller commit.

Repeated successful stop is idempotent through `NotRunning`.

## No output/drain contract

The generic adapter interface does not expose provider output, final messages, terminal events, tool streams, or drain completion to controller progression.

An adapter may privately consume SDK/stdout streams when its library or child process requires that for transport health. It discards or sends bounded sanitized diagnostics to its own support logger. The runtime does not wait for those streams and never interprets them as assignment truth.

There is no 30-second provider drain phase, final-response grace period, provider-terminal callback, or `agent.wait` correctness path.

## Managed MCP injection

For Codex and Claude, the adapter dynamically supplies the managed MCP URL, bearer credential, and exact tool allowlist for one dispatch. It does not write this material to user/global/project provider configuration.

The stable adapter invariant is dynamic nonpersistent injection. Exact SDK/app-server fields are provider-version conformance details and must be proven against the pinned supported version.

Multiple concurrent dispatches share one MCP server but receive different credentials and allowlists. Provider session/thread continuity does not reuse a credential; every retry or successor gets a fresh binding.

## OpenClaw compatibility

OpenClaw stays externally installed and supervised. Its adapter may start/cancel an explicitly selected experimental dispatch through documented Gateway behavior, but AutoClaw does not:

- install or supervise the Gateway;
- mutate `openclaw.json` or global MCP/tool policy;
- infer authority from Gateway session/run IDs;
- wait on `agent.wait` or output for correctness;
- auto-fallback from a failed explicit route; or
- hide the explicit-ID compatibility schema.

Workspace/cwd, start acceptance, cancellation, restart ambiguity, and version support remain pinned experimental conformance cases.

## Provider check

`check()` is a bounded non-agent diagnostic used only by the explicit provider-check command. It may inspect native installation/configuration/authentication/reachability using documented provider surfaces.

It must not create a task/dispatch/binding, run a model turn, invoke Node MCP, mutate provider configuration, or persist readiness.

Runtime dispatch start does not run the full check first. Deterministic local request/provider-route validation occurs before D2 commit; the real adapter handshake occurs after commit and retries as owned by runtime.

## Lifecycle

Adapter resources are created and closed by the main FastAPI lifespan. The adapter may expose an async context manager or equivalent internal resource factory, but request handlers and model-facing code do not manually orchestrate public `start()`/`close()` lifecycle pairs.

Shutdown revokes managed bindings first, cancels local output consumers, then closes owned transports or requests bounded provider/process cleanup. It does not wait for final output or drain, and cleanup cannot rewrite already committed controller state.

Process restart discards provider-private handles. Startup recovery treats current `starting` dispatches conservatively as potentially uncertain and re-enters the stop-and-retry path.

## Security and logging

Adapters run under the AutoClaw service identity and provider-native home. They never copy provider credentials into controller storage.

Logs and errors may include canonical non-secret provider route, task ID, dispatch ID, operation, timing, and normalized code. They exclude:

- provider credentials and auth payloads;
- managed MCP bearer credentials or digests;
- raw provider input/output;
- raw environment values;
- human answers and command logs; and
- provider session/thread IDs presented as authority.

## Conformance matrix

Every adapter must prove:

- exact two-lane request delivery from committed refs;
- no provider call before D2+refs commit;
- dynamic managed MCP injection or explicit compatibility configuration;
- correct role-specific tool allowlist behavior;
- definite versus uncertain start classification where the provider permits;
- bounded stop semantics and `NotRunning` idempotency when supported;
- same-D2 retry without prompt rerender;
- no provider final/output progression;
- service-identity/native-home consistency across status, check, and runtime; and
- secret/log/readback redaction.

OpenClaw additionally records exact-version conformance gaps without globally disabling its experimental route.

## Removed target concepts

- `start(prompt, provider_session_hint)` as a combined prompt contract;
- generic persisted provider session/run hints;
- finite six-call start/stop budgets;
- provider final/EOF/tool events as controller inputs;
- generic output drain or terminal wait;
- provider fallback inside one committed dispatch; and
- adapter-owned Node operation or controller validation logic.

## Related

- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Managed Node MCP binding](managed-node-mcp-binding.md)
- [Prompt system](../prompt-layer/prompt-system.md)
- [Provider selection and runtime config](../interfaces/provider-selection-and-runtime-config.md)
- [Provider support and compatibility](../interfaces/provider-support-and-compatibility.md)

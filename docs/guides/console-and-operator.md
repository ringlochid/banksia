# Use the Console and Operator

The Console and Operator are two product surfaces over the same controller truth.

## Console

Start the local application:

```bash
banksia serve
```

The default address is `http://127.0.0.1:18125/`. Current routes include:

- `/workflows` for the Workflow library;
- `/workflows/{id}` for draft review and editing;
- `/runs` for Task history;
- `/runs/new` for Task start; and
- `/runs/{task-id}` for Task progress, waits, controls, and technical detail.

The current Console is functional but temporary. It supports the main authoring and operating paths while the final visual studio is still being developed. Desktop is the current design priority; mobile and tablet polish are deferred.

## Operator

The Operator is a separate Codex or Claude agent with controller product operations. It can:

- search and inspect Workflows;
- inspect authoring options;
- create, edit, validate, undo, discard, and publish drafts;
- search, inspect, start, pause, resume, and cancel Tasks;
- answer Human Requests; and
- inspect or cancel Command Runs and read their bounded output.

The Operator is not a Task Member and cannot call runtime delegation, Checkpoint, replan, or Task-member context operations. It also has no generic host filesystem, shell, network, artifact, or file-read authority. Workflow drafting uses JSON-compatible structured operations; users do not need to write YAML in the conversation.

When the Codex adapter needs provider-native isolated code mode to compose structured calls, that runtime remains adapter-private and receives only the Operator operation catalog plus inert planning. It does not receive a host execution environment or extra Banksia authority.

## Clarification flow

When a request is underspecified, the Operator can return a typed question set instead of guessing. The Console renders two or three suggested options and an allowed free-form choice when appropriate. The user submits an explicit answer, and the next Operator turn rereads the persisted conversation and controller state before continuing.

The Operator can also return a final answer with links to the Workflow, Task, Human Request, or Command Run it changed. These two output forms—clarification or final answer—keep the interaction small while controller operations perform the actual work.

## Configure the Operator

Choose one configured managed provider in `config.toml`:

```toml
[operator]
provider = "codex"
model = "gpt-5.6"
effort = "high"
```

`provider` may be `codex` or `claude`. Model and effort are optional. The selected provider must also be enabled and authenticated in its provider section.

The Operator HTTP routes are same-origin local product routes. They are not an external MCP server and do not make Operator tools authorable inside a Workflow.
